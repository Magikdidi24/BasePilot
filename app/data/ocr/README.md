# OCR model

`en_PP-OCRv4_rec_mobile.onnx`: PaddleOCR's English PP-OCRv4 mobile recognition model, in the
ONNX export published by RapidOCR (v3.10.0 model hub, `onnx/PP-OCRv4/rec/`), SHA-256
`e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318`.
`en_dict.txt` is its character list, taken from the model's metadata (one per line, the last
one a space). Both are under the Apache License 2.0 (PaddleOCR, RapidOCR).

`app/services/ppocr.py` runs it with OpenCV's DNN module to read the HUD resource numbers.
