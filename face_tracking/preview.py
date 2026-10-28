"""Compact face annotations over the existing resized, unmirrored preview."""

import cv2


def draw_faces(preview, observation):
    height, width = preview.shape[:2]
    if observation is None or not observation.faces:
        label = "FACE: expired" if observation is not None and observation.status == "expired" else "FACE: none"
    else:
        for index, face in enumerate(observation.faces):
            box = face.box_normalized
            p1 = (min(width-1, round(box.x_min*width)), min(height-1, round(box.y_min*height)))
            p2 = (min(width-1, round(box.x_max*width)), min(height-1, round(box.y_max*height)))
            center = (min(width-1, round((box.x_min+box.x_max)/2*width)),
                      min(height-1, round((box.y_min+box.y_max)/2*height)))
            color = (0, 220, 255) if index == observation.primary_index else (220, 180, 0)
            cv2.rectangle(preview, p1, p2, color, 1, cv2.LINE_AA)
            cv2.circle(preview, center, 3, color, -1, cv2.LINE_AA)
            score = f" {face.confidence:.0%}" if face.confidence is not None else ""
            cv2.putText(preview, f"FACE {index+1}{score}", (p1[0], max(12, p1[1]-4)),
                        cv2.FONT_HERSHEY_SIMPLEX, .4, color, 1, cv2.LINE_AA)
            if index == observation.primary_index:
                cv2.line(preview, (width//2, height//2), center, color, 1, cv2.LINE_AA)
        primary = observation.primary
        label = f"FACE 1 | X: {primary.normalized_offset_x:+.2f} | Y: {primary.normalized_offset_y:+.2f}"
    # Bottom strip avoids the existing top status/control rows.
    cv2.putText(preview, label, (8, max(12, height-8)), cv2.FONT_HERSHEY_SIMPLEX, .45,
                (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(preview, label, (8, max(12, height-8)), cv2.FONT_HERSHEY_SIMPLEX, .45,
                (0, 220, 255), 1, cv2.LINE_AA)
