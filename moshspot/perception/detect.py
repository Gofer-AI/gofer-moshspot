"""Full-frame person detection with a YOLO detection model run by the OpenCV 5 DNN engine."""

import numpy as np

from moshspot.perception.yolo import center_to_corners, letterbox, load_net, nms, to_blob

PERSON_CLASS = 0


class PersonDetector:
    """Ultralytics YOLO detection model (output 1 x (4 + classes) x anchors), filtered to people."""

    def __init__(self, model_path, input_size=640, conf_threshold=0.25, nms_threshold=0.45, engine="new"):
        self.net = load_net(model_path, engine)
        self.input_size = input_size
        self.conf_threshold = conf_threshold
        self.nms_threshold = nms_threshold

    def preprocess(self, frame):
        padded, box = letterbox(frame, self.input_size)
        return to_blob([padded]), box

    def infer(self, blob):
        self.net.setInput(blob)
        return self.net.forward()

    def postprocess(self, output, letterbox_):
        preds = output[0].T
        scores = preds[:, 4 + PERSON_CLASS]
        mask = scores > self.conf_threshold
        if not mask.any():
            return np.zeros((0, 4)), np.zeros(0)
        boxes, scores = center_to_corners(preds[mask, :4]), scores[mask]
        keep = nms(boxes, scores, self.conf_threshold, self.nms_threshold)
        corners = letterbox_.to_frame(boxes[keep].reshape(-1, 2, 2)).reshape(-1, 4)
        return corners, scores[keep]

    def detect(self, frame):
        """Person boxes (N, 4) as x1, y1, x2, y2 in frame pixels, and their scores (N,)."""
        blob, letterbox_ = self.preprocess(frame)
        return self.postprocess(self.infer(blob), letterbox_)

    def detect_tiled(self, frame, grid=(2, 2), overlap=0.2):
        """The full frame plus an overlapping grid of tiles, merged with NMS.

        Distant people in a 1280x720 crowd shot are 15-30 px tall; downscaled to the 640 px model input
        they mostly vanish. Each tile is seen at twice the scale (sim test: 0-26 -> 22-46 people per frame).
        """
        h, w = frame.shape[:2]
        tile_h, tile_w = h / grid[0], w / grid[1]
        all_boxes, all_scores = [], []
        for row in range(grid[0]):
            for col in range(grid[1]):
                y0, y1 = max(0, int((row - overlap) * tile_h)), min(h, int((row + 1 + overlap) * tile_h))
                x0, x1 = max(0, int((col - overlap) * tile_w)), min(w, int((col + 1 + overlap) * tile_w))
                boxes, scores = self.detect(frame[y0:y1, x0:x1])
                all_boxes.append(boxes + (x0, y0, x0, y0))
                all_scores.append(scores)
        boxes, scores = self.detect(frame)
        boxes, scores = np.vstack(all_boxes + [boxes]), np.concatenate(all_scores + [scores])
        if not len(boxes):
            return boxes, scores
        keep = nms(boxes, scores, self.conf_threshold, self.nms_threshold)
        return boxes[keep], scores[keep]
