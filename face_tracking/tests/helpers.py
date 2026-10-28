from types import SimpleNamespace as NS


def detection(x=160, y=90, w=320, h=180, score=.9):
    return NS(bounding_box=NS(origin_x=x, origin_y=y, width=w, height=h),
              categories=[NS(score=score)] if score is not None else [])


def result(*detections):
    return NS(detections=list(detections))


MP = NS(Image=lambda **kwargs: kwargs['data'], ImageFormat=NS(SRGB=1))
