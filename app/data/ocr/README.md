# OCR models

PaddleOCR's PP-OCRv6 (Apache License 2.0), in the ONNX export RapidOCR publishes (v3.10.0
model hub, `onnx/PP-OCRv6/`):

| File | Model | SHA-256 |
|---|---|---|
| `PP-OCRv6_det_tiny.onnx` | text detector (tiny) | `f42c0fbd294d95eac1a550e131b277dac97462c8025fa4b6c3cec1b7894bd3d5` |
| `PP-OCRv6_rec_small.onnx` | line recognizer (small) | `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` |

`PP-OCRv6_rec_small_dict.txt` is the recognizer's character list (18 708 characters: Latin,
Chinese, Japanese...), taken from the model's metadata (`character`), one per line. The
decoder puts the CTC blank before it and a space after it.

`app/services/ppocr.py` runs them with ONNX Runtime, else OpenCV's DNN module, for every
text the bot reads on screen: labels, Build panel cards, HUD numbers, results screens.
