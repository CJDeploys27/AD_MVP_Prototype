# utilities/privacy_guard.py
import cv2
import numpy as np

def blur_faces_in_image(image_bytes: bytes) -> bytes:
    """
    Detects and blurs faces in an image using OpenCV's Haar Cascades.
    Returns the sanitized image as bytes.
    """
    # 1. Convert raw bytes to an OpenCV image array
    np_arr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    
    if img is None:
        return image_bytes # Return original if decoding fails

    # 2. Load the lightweight pre-trained face detection model
    # OpenCV includes this XML file by default in its package
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    
    # Convert to grayscale for the detection algorithm
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Detect faces
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    
    # 3. Apply a strong Gaussian Blur to any detected bounding boxes
    for (x, y, w, h) in faces:
        # Extract the region of interest (the face)
        roi = img[y:y+h, x:x+w]
        # Apply blur (kernel size must be odd numbers, larger = blurrier)
        blurred = cv2.GaussianBlur(roi, (99, 99), 30)
        # Put the blurred region back into the main image
        img[y:y+h, x:x+w] = blurred

    # 4. Encode the sanitized image back to bytes
    success, encoded_img = cv2.imencode('.jpg', img)
    if success:
        return encoded_img.tobytes()
    
    return image_bytes
