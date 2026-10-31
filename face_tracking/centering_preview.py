"""Small annotations on the existing preview; no new GUI or frame ownership."""

import cv2

from .centering import CenteringStatus


def draw_centering(preview, result, *, now, config, debug=False):
    """Return whether a previously available result became stale before drawing."""
    height, width = preview.shape[:2]
    fresh = result.fresh_at(now)
    expired = result.actionable and not fresh
    color = (80, 230, 80) if fresh and result.is_centered else (0, 190, 255)
    if result.frame_size is not None and result.target_center is not None:
        fw, fh = result.frame_size
        def point(x, y):
            return max(0, min(width-1, round(x/fw*width))), max(0, min(height-1, round(y/fh*height)))
        tx, ty = result.target_center
        target = point(tx, ty)
        cv2.line(preview, (max(0,target[0]-5),target[1]), (min(width-1,target[0]+5),target[1]), color, 1, cv2.LINE_AA)
        cv2.line(preview, (target[0],max(0,target[1]-5)), (target[0],min(height-1,target[1]+5)), color, 1, cv2.LINE_AA)
        if debug:
            for x, y, zone_color in ((config.horizontal.activation, config.vertical.activation, (110,110,110)),
                                     (config.horizontal.deactivation, config.vertical.deactivation, (80,130,80))):
                cv2.rectangle(preview, point(tx-x*fw/2, ty-y*fh/2), point(tx+x*fw/2, ty+y*fh/2), zone_color, 1, cv2.LINE_AA)
        if fresh and result.smoothed_center is not None:
            face = point(*result.smoothed_center)
            cv2.circle(preview, face, 4, color, 1, cv2.LINE_AA)
            if result.is_centered:
                cv2.line(preview, target, face, color, 1, cv2.LINE_AA)
            else:
                cv2.arrowedLine(preview, target, face, color, 1, cv2.LINE_AA, tipLength=.15)
    if fresh:
        directions = [str(axis.direction).replace('_', ' ') for axis in (result.horizontal, result.vertical) if axis.active]
        lines = [f"CENTERING: {result.status}" + (" | " + " / ".join(directions) if directions else ""),
                 f"ERR X:{result.horizontal.error:+.2f} Y:{result.vertical.error:+.2f} | DEMAND X:{result.horizontal.demand:+.2f} Y:{result.vertical.demand:+.2f}"]
    else:
        status = CenteringStatus.STALE_OBSERVATION if expired else result.status
        lines = [f"CENTERING PAUSED | {status}"]
    # Above the existing face bottom strip; hand status rows remain unchanged.
    for index, line in enumerate(lines):
        origin = (8, max(12, height-44+index*17))
        cv2.putText(preview, line, origin, cv2.FONT_HERSHEY_SIMPLEX, .4, (0,0,0), 3, cv2.LINE_AA)
        cv2.putText(preview, line, origin, cv2.FONT_HERSHEY_SIMPLEX, .4, color, 1, cv2.LINE_AA)
    return expired
