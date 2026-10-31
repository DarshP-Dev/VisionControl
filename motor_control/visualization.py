"""Two simple views of actual virtual state. No GUI, camera or input ownership."""

import math
import time

import cv2
import numpy as np


class MotorRenderer:
    def __init__(self,*,debug=False):
        self.debug=debug
        self.buffer=None

    def close(self):self.buffer=None

    def render(self,state,config,*,profile=None):
        measured=profile is not None and profile.enabled
        start=time.perf_counter() if measured else None
        if self.buffer is None:self.buffer=np.empty((390 if self.debug else 330,540,3),np.uint8)
        canvas=self.buffer
        canvas.fill(28)  # Fast byte fill; avoid broadcasting a color tuple per pixel.
        def text(label,x,y,scale=.43,color=(225,225,225)):
            cv2.putText(canvas,label,(x,y),cv2.FONT_HERSHEY_SIMPLEX,scale,color,1,cv2.LINE_AA)
        text('MOTOR SIMULATION - HARDWARE OUTPUT DISABLED',12,22,.49,(50,220,255))
        # Top view: forward is up on the panel, positive pan turns toward right.
        origin=(130,130)
        cv2.circle(canvas,origin,60,(105,105,105),1,cv2.LINE_AA)
        cv2.rectangle(canvas,(90,160),(170,176),(90,90,90),-1)
        cv2.line(canvas,origin,(130,62),(90,90,90),1,cv2.LINE_AA)
        for angle in (config.pan.minimum_deg,config.pan.maximum_deg):
            a=math.radians(angle)
            cv2.line(canvas,origin,(round(origin[0]+58*math.sin(a)),round(origin[1]-58*math.cos(a))),(80,100,170),1,cv2.LINE_AA)
        p=math.radians(state.pan.angle_deg)
        platform=cv2.boxPoints(((130,130),(42,32),state.pan.angle_deg))
        cv2.fillConvexPoly(canvas,np.rint(platform).astype(np.int32),(120,100,75),cv2.LINE_AA)
        endpoint=(round(origin[0]+48*math.sin(p)),round(origin[1]-48*math.cos(p)))
        cv2.arrowedLine(canvas,origin,endpoint,(40,220,230),3,cv2.LINE_AA,tipLength=.2)
        cv2.circle(canvas,origin,7,(220,130,50),-1,cv2.LINE_AA)
        text('PAN / TOP VIEW (+right)',45,199,.4)
        # Side view: positive tilt points down. Base/pivot stay fixed.
        pivot=(382,124)
        cv2.rectangle(canvas,(352,158),(418,176),(90,90,90),-1)
        cv2.line(canvas,(382,168),pivot,(180,130,60),5,cv2.LINE_AA)
        t=math.radians(state.tilt.angle_deg)
        forward=(round(pivot[0]+55*math.cos(t)),round(pivot[1]+55*math.sin(t)))
        corners=cv2.boxPoints(((382,124),(58,27),state.tilt.angle_deg))
        cv2.fillConvexPoly(canvas,np.rint(corners).astype(np.int32),(120,100,75),cv2.LINE_AA)
        cv2.arrowedLine(canvas,pivot,forward,(40,220,230),2,cv2.LINE_AA,tipLength=.18)
        cv2.circle(canvas,pivot,5,(220,130,50),-1,cv2.LINE_AA)
        for angle in (config.tilt.minimum_deg,config.tilt.maximum_deg):
            a=math.radians(angle)
            cv2.line(canvas,pivot,(round(pivot[0]+62*math.cos(a)),round(pivot[1]+62*math.sin(a))),(80,100,170),1,cv2.LINE_AA)
        text('TILT / SIDE VIEW (+down)',285,199,.4)
        if state.pan.at_minimum or state.pan.at_maximum:text('PAN LIMIT',183,87,.37,(80,110,255))
        if state.tilt.at_minimum or state.tilt.at_maximum:text('TILT LIMIT',443,175,.34,(80,110,255))
        text(f'PAN {state.pan.angle_deg:+6.1f} deg | {state.pan.velocity_deg_s:+5.1f} deg/s | target {state.pan.target_velocity_deg_s:+5.1f}',12,225)
        text(f'TILT {state.tilt.angle_deg:+5.1f} deg | {state.tilt.velocity_deg_s:+5.1f} deg/s | target {state.tilt.target_velocity_deg_s:+5.1f}',12,246)
        target=f"FACE #{state.command.tracking_id}" if state.command.tracking_id is not None else 'NO TARGET'
        text(f'{target} | {state.status} | {state.reason}',12,269,.40,(75,220,250))
        text(f'Limits PAN [{config.pan.minimum_deg:g},{config.pan.maximum_deg:g}] TILT [{config.tilt.minimum_deg:g},{config.tilt.maximum_deg:g}] deg',12,291,.39)
        text('Real webcam stays fixed; virtual rotation cannot recenter its image.',12,315,.36,(170,180,190))
        if self.debug:
            text(f'Request PAN {state.command.requested.pan_deg_s:+.2f} TILT {state.command.requested.tilt_deg_s:+.2f} deg/s',12,341,.4)
            text(f'Command valid={state.command.valid} | actual detection time={state.command.observation_timestamp}',12,362,.36)
            text('Illustrative mechanism only; no real position/torque measurement.',12,382,.36)
        if measured:profile.add('motor_visualization',time.perf_counter()-start)
        return canvas
