"""Cheap local frame measurements, adapted from UltraCut's analysis primitives.

Measurements are heuristics, not semantic labels. In particular, a low-texture
sky is not proof of blur, and optical flow does not identify people or emotion.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field

import cv2
import numpy as np


LOCAL_ANALYSIS_VERSION = "opencv-hsv-quality-phash-v3"


def _scaled_gray(frame):
    height, width = frame.shape[:2]
    scale = min(1.0, 320.0 / max(width, height))
    if scale < 1:
        frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _estimate_transform(previous, current):
    points = cv2.goodFeaturesToTrack(previous, maxCorners=160, qualityLevel=0.01, minDistance=8, blockSize=3)
    if points is None or len(points) < 8:
        return None
    following, status, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
    if following is None or status is None:
        return None
    valid = status.reshape(-1) == 1
    if np.count_nonzero(valid) < 8:
        return None
    transform, inliers = cv2.estimateAffinePartial2D(points[valid], following[valid], method=cv2.RANSAC)
    if transform is None or inliers is None or float(inliers.mean()) < 0.5:
        return None
    return transform


def _phash(gray):
    square = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    coefficients = cv2.dct(square)[:8, :8].reshape(-1)
    bits = coefficients > np.median(coefficients[1:])
    bits[0] = False
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


@dataclass(slots=True)
class FrameFeatureAnalyzer:
    previous: np.ndarray | None = None
    smooth_transform: np.ndarray = field(default_factory=lambda: np.zeros(3))

    def measure(self, frame, reset_motion=False) -> dict[str, float]:
        gray = _scaled_gray(frame)
        texture = float(gray.std())
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        features = {
            "sharpness": sharpness,
            "brightness": float(gray.mean()) / 255,
            "dark_fraction": float(np.mean(gray < 12)),
            "bright_fraction": float(np.mean(gray > 243)),
            "texture": texture,
            "blur_confidence": min(1.0, texture / 24) if texture >= 8 else 0.0,
            "motion": 0.0, "jitter": 0.0, "motion_confidence": 0.0,
            "hash_confidence": 1.0 if texture >= 8 and sharpness >= 2 else 0.0,
        }
        # Four exact 16-bit words survive JSON and numeric feature storage.
        signature = _phash(gray)
        for index in range(4):
            features[f"hash_{index}"] = float((signature >> (index * 16)) & 0xFFFF)
        for index, value in enumerate(frame.reshape(-1, 3).mean(axis=0) / 255):
            features[f"color_{index}"] = float(value)
        if reset_motion:
            self.previous = None
            self.smooth_transform = np.zeros(3)
        if self.previous is not None and self.previous.shape == gray.shape:
            transform = _estimate_transform(self.previous, gray)
            if transform is not None:
                current = np.array([float(transform[0, 2]), float(transform[1, 2]),
                                    math.atan2(float(transform[1, 0]), float(transform[0, 0])) * 100])
                self.smooth_transform = self.smooth_transform * 0.75 + current * 0.25
                features["motion"] = float(np.linalg.norm(current))
                features["jitter"] = float(np.linalg.norm(current - self.smooth_transform))
                features["motion_confidence"] = 1.0
        self.previous = gray
        return features


def technical_quality(features: dict[str, float]) -> float:
    """A bounded soft preference; never a hard rejection of a family memory."""
    blur = (80 / (80 + features["sharpness"])) * features["blur_confidence"]
    exposure = max(features["dark_fraction"], features["bright_fraction"])
    jitter = min(1.0, features["jitter"] / 18) * features["motion_confidence"]
    return max(0.0, min(1.0, 1 - 0.5 * exposure - 0.3 * blur - 0.2 * jitter))


def visual_signature(features):
    if features.get("hash_confidence", 0) < 0.5:
        return None
    try:
        value = sum(int(features[f"hash_{index}"]) << (index * 16) for index in range(4))
        colors = tuple(float(features[f"color_{index}"]) for index in range(3))
    except (KeyError, TypeError, ValueError):
        return None
    return value, colors


def visual_similarity(left, right):
    """Require a sequence of textured samples; uniform frames never prove a duplicate."""
    if len(left) < 3 or len(right) < 3:
        return 0.0
    similarities = []
    for first, second in zip(left, right):
        distance = (first[0] ^ second[0]).bit_count()
        color_difference = max(abs(a - b) for a, b in zip(first[1], second[1]))
        if distance > 8 or color_difference > 0.08:
            return 0.0
        similarities.append((1 - distance / 64) * (1 - color_difference))
    return min(similarities, default=0.0)


class LocalFeatureIndex:
    def __init__(self, windows):
        self.windows = sorted(windows, key=lambda window: window.start_seconds)
        self.starts = [window.start_seconds for window in self.windows]

    def summarize(self, start, end):
        first = max(0, bisect_right(self.starts, start) - 1)
        last = bisect_left(self.starts, end)
        entries = []
        for window in self.windows[first:last]:
            overlap = min(end, window.end_seconds) - max(start, window.start_seconds)
            if overlap > 0:
                entries.append((window.features, overlap))
        coverage = sum(weight for _, weight in entries) / (end - start)
        if coverage < 0.5 or not entries:
            return None, (), ()
        total = sum(weight for _, weight in entries)

        def mean(key):
            return sum(features[key] * weight for features, weight in entries) / total

        quality = sum(technical_quality(features) * weight for features, weight in entries) / total
        notes = []
        if mean("dark_fraction") > 0.4:
            notes.append("Lokale Stichproben: viele dunkle Bildbereiche")
        if mean("bright_fraction") > 0.4:
            notes.append("Lokale Stichproben: viele sehr helle Bildbereiche")
        if mean("blur_confidence") > 0.5 and mean("sharpness") < 80:
            notes.append("Lokale Stichproben: mögliche Unschärfe")
        if mean("motion_confidence") > 0.5 and mean("jitter") > 10:
            notes.append("Lokale Stichproben: möglicherweise unruhige Kamerabewegung")
        if not notes:
            notes.append("Lokale Stichproben ohne starke technische Auffälligkeiten")
        signatures = ()
        if coverage >= 0.75 and len(entries) >= 3:
            points = [visual_signature(entries[index][0]) for index in (0, len(entries) // 2, len(entries) - 1)]
            if all(point is not None for point in points):
                signatures = tuple(points)
        return quality, signatures, tuple(notes)
