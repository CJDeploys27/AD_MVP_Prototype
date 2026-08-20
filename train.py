import os
import io
import sys
import json
import argparse
from PIL import Image

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import models, transforms

# ---------------------------------------------------------------------------
# PostGIS Taxonomy Index Mapping (Class ID -> Canonical Code)
# ---------------------------------------------------------------------------
CLASS_ID_TO_CANONICAL = {
    0: "ziziphus_mauritiana",       # Chinee Apple
    1: "lantana_camara",           # Lantana
    2: "parkinsonia_aculeata",     # Parkinsonia
    3: "parthenium_hysterophorus", # Parthenium
    4: "vachellia_nilotica",       # Prickly Acacia
    5: "cryptostegia_grandiflora", # Rubber Vine
    6: "chromolaena_odorata",      # Siam Weed
    7: "stachytarpheta_spp",       # Snake Weed
    8: "negatives"                  # Background / Soil
}

# Standard ImageNet normalization transforms for lightweight MobileNetV3
INFERENCE_TRANSFORMS = transforms.Compose([
    transforms.Resize((224, 224)),
    transforms.ToTensor(),
    transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

def build_model(num_classes=9):
    """Instantiates a lightweight MobileNetV3-Small vision backbone."""
    model = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
    in_features = model.classifier[3].in_features
    model.classifier[3] = nn.Linear(in_features, num_classes)
    return model

# ---------------------------------------------------------------------------
# 1. Training Execution (SageMaker Entrypoint)
# ---------------------------------------------------------------------------
def train():
    parser = argparse.ArgumentParser()
    
    # Standard SageMaker Container Environment Flags
    parser.add_argument('--model-dir', type=str, default=os.environ.get('SM_MODEL_DIR', './model'))
    parser.add_argument('--train', type=str, default=os.environ.get('SM_CHANNEL_TRAIN', './data'))
    parser.add_argument('--epochs', type=int, default=5)
    parser.add_argument('--batch-size', type=int, default=32)
    parser.add_argument('--lr', type=float, default=0.001)
    parser.add_argument('--num-classes', type=int, default=9)

    args = parser.parse_args()
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"🚀 Training MobileNetV3 on device: {device}")

    model = build_model(num_classes=args.num_classes).to(device)
    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=args.lr)

    # Note: When integrated with SageMaker Channels, dataset loading reads from args.train
    print(f"📦 Training channel path: {args.train}")
    
    model.train()
    for epoch in range(args.epochs):
        print(f"Epoch {epoch + 1}/{args.epochs} executing...")
        # Synthetic loop structure for demonstration during dry-run testing
        optimizer.zero_grad()
        dummy_input = torch.randn(args.batch_size, 3, 224, 224).to(device)
        dummy_labels = torch.zeros(args.batch_size, dtype=torch.long).to(device)
        output = model(dummy_input)
        loss = criterion(output, dummy_labels)
        loss.backward()
        optimizer.step()
        print(f"  └─ Epoch {epoch + 1} Loss: {loss.item():.4f}")

    # Save model weights and taxonomy catalog mapping
    os.makedirs(args.model_dir, exist_ok=True)
    model_path = os.path.join(args.model_dir, "model.pth")
    mapping_path = os.path.join(args.model_dir, "taxonomy_mapping.json")

    torch.save(model.state_dict(), model_path)
    with open(mapping_path, 'w') as f:
        json.dump(CLASS_ID_TO_CANONICAL, f)

    print(f"✨ Saved PyTorch model artifact to {model_path}")

# ---------------------------------------------------------------------------
# 2. SageMaker Inference Serving Entrypoints
# ---------------------------------------------------------------------------
def model_fn(model_dir):
    """Loads saved PyTorch weights and class taxonomy mappings into GPU/CPU memory."""
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    mapping_path = os.path.join(model_dir, "taxonomy_mapping.json")
    if os.path.exists(mapping_path):
        with open(mapping_path, 'r') as f:
            raw_map = json.load(f)
            taxonomy_map = {int(k): v for k, v in raw_map.items()}
    else:
        taxonomy_map = CLASS_ID_TO_CANONICAL

    model = build_model(num_classes=len(taxonomy_map))
    model_path = os.path.join(model_dir, "model.pth")
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path, map_location=device))
    
    model.to(device).eval()
    return {"model": model, "taxonomy_map": taxonomy_map, "device": device}

def input_fn(request_body, request_content_type='application/x-image'):
    """Deserializes raw HTTP image byte streams into PyTorch tensors."""
    if request_content_type in ['image/jpeg', 'image/png', 'application/x-image']:
        image = Image.open(io.BytesIO(request_body)).convert('RGB')
        tensor = INFERENCE_TRANSFORMS(image).unsqueeze(0)
        return tensor
    elif request_content_type == 'application/json':
        data = json.loads(request_body)
        if "image_bytes" in data:
            import base64
            img_bytes = base64.b64decode(data["image_bytes"])
            image = Image.open(io.BytesIO(img_bytes)).convert('RGB')
            return INFERENCE_TRANSFORMS(image).unsqueeze(0)
    raise ValueError(f"Unsupported content type: {request_content_type}")

def predict_fn(input_tensor, model_assets):
    """Runs input tensor through forward pass and applies Softmax probabilities."""
    model = model_assets["model"]
    taxonomy_map = model_assets["taxonomy_map"]
    device = model_assets["device"]

    input_tensor = input_tensor.to(device)
    with torch.no_grad():
        outputs = model(input_tensor)
        probabilities = torch.nn.functional.softmax(outputs, dim=1)[0]
        confidence, class_id = torch.max(probabilities, dim=0)

    class_idx = class_id.item()
    return {
        "canonical_code": taxonomy_map.get(class_idx, "negatives"),
        "class_id": class_idx,
        "confidence": round(confidence.item(), 4)
    }

def output_fn(prediction, response_content_type='application/json'):
    """Serializes prediction dictionary to JSON string matching Streamlit expectation."""
    if response_content_type == 'application/json':
        return json.dumps(prediction), 'application/json'
    raise ValueError(f"Unsupported response content type: {response_content_type}")

if __name__ == '__main__':
    train()