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


def draw_tracks(preview, observation, *, now, debug=False):
    """Only draw currently fresh detections, including after a slow GUI restore."""
    height, width = preview.shape[:2]
    primary = observation.primary
    for track in observation.tracks:
        if not track.detected or now-track.last_detected > .25:
            continue
        face = track.smoothed
        b = face.box_normalized
        point = lambda x, y: (max(0, min(width-1, round(x*width))), max(0, min(height-1, round(y*height))))
        p1, p2 = point(b.x_min, b.y_min), point(b.x_max, b.y_max)
        center = point(face.normalized_center_x, face.normalized_center_y)
        color = (0, 220, 255) if track.primary else (220, 180, 0) if track.state == "TRACKED" else (150, 150, 150)
        cv2.rectangle(preview, p1, p2, color, 2 if track.primary else 1, cv2.LINE_AA)
        cv2.circle(preview, center, 3, color, -1, cv2.LINE_AA)
        if debug:
            raw = point(track.raw.normalized_center_x, track.raw.normalized_center_y)
            cv2.circle(preview, raw, 4, (220, 50, 220), 1, cv2.LINE_AA)
            cv2.line(preview, raw, center, (220, 50, 220), 1, cv2.LINE_AA)
        label = f"FACE #{track.track_id} | {track.state}" + (" | PRIMARY" if track.primary else "")
        cv2.putText(preview, label, (p1[0], max(12, p1[1]-4)), cv2.FONT_HERSHEY_SIMPLEX, .4, color, 1, cv2.LINE_AA)
    if primary is None:
        label = "FACE: unlocked"
    elif not primary.detected or now-primary.last_detected > .25:
        label = f"FACE #{primary.track_id} | PRIMARY LOST" + (" | UNCERTAIN" if primary.uncertain else "")
    else:
        face = primary.smoothed
        label = f"FACE #{primary.track_id} | PRIMARY | X: {face.normalized_offset_x:+.2f} | Y: {face.normalized_offset_y:+.2f}"
    if observation.status != "valid":
        label += f" | {observation.status}"
    cv2.putText(preview, label, (8, max(12, height-8)), cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(preview, label, (8, max(12, height-8)), cv2.FONT_HERSHEY_SIMPLEX, .45, (0, 220, 255), 1, cv2.LINE_AA)
