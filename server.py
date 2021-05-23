import json
import logging
import os
import ssl
import uuid
import numpy as np

import cv2 as cv
from aiohttp import web
from av import VideoFrame

from aiortc import MediaStreamTrack, RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaBlackhole, MediaPlayer, MediaRecorder

ROOT = os.path.dirname(__file__)

logger = logging.getLogger("pc")
pcs = set()

List = [ [ ] ]
cList = [[]]
isDrawing = False

def nothing(x):
	pass
	pass

def render_lines(x, y):
	global List, cList
	b,g,r = (0, 0, 0)
	List[-1].append([x, y])
	cList[-1].append([int(b),int(g),int(r)])

def clear(event, x, y, flags, params):
	global List, cList
	if event == cv.EVENT_FLAG_LBUTTON:
		List = [[]]
		cList = [[]]


# def calibration(frameO):
# 	global cap

# 	cv.namedWindow("calibration")
# 	cv.createTrackbar('hue lower', 'calibration', 50, 179, nothing)
# 	cv.createTrackbar('hue upper', 'calibration', 130, 179, nothing)
# 	cv.createTrackbar('sat lower', 'calibration', 90,255,nothing)
# 	cv.createTrackbar('sat upper', 'calibration', 255,255,nothing)
# 	cv.createTrackbar('vib lower', 'calibration', 60, 255, nothing)
# 	cv.createTrackbar('vib upper', 'calibration', 189, 255, nothing)
# 	cv.createTrackbar('start app', 'calibration', 0, 1, nothing)

# 	_, frameO = cap.read()
# 	frame = cv.flip(frameO, 1)
# 	hsv = cv.cvtColor(frame, cv.COLOR_BGR2HSV)

# 	hl = cv.getTrackbarPos('hue lower', 'calibration')
# 	hu = cv.getTrackbarPos('hue upper', 'calibration')
# 	sl = cv.getTrackbarPos('sat lower', 'calibration')
# 	su = cv.getTrackbarPos('sat upper', 'calibration')
# 	vl = cv.getTrackbarPos('vib lower', 'calibration')
# 	vu = cv.getTrackbarPos('vib upper', 'calibration')

# 	lower = np.array([hl,sl,vl])
# 	range = np.array([hu,su,vu])

# 	rows,cols,chan = frame.shape
# 	temp = frame[20:rows-20, 20:cols-20]
# 	mask = cv.inRange(hsv, lower, range)
	
# 	tempmask = mask[20:rows-20, 20:cols-20]
# 	tempres = cv.bitwise_and(temp, temp, mask=tempmask)
# 	res = cv.copyMakeBorder(tempres, 20,20,20, 20, cv.BORDER_CONSTANT, value=[0,0,0])

# 	return (hl, hu, sl, su, vl, vu)

def canvas(raw_frame):

	global cap, List, cList , isDrawing
	hl, hu, sl, su, vl, vu = [50,130,90,255,60,189]
	
	
	frame = cv.flip(raw_frame, 1)
	hsv = cv.cvtColor(frame, cv.COLOR_BGR2HSV)

	lower = np.array([hl,sl,vl])
	ranges = np.array([hu,su,vu])

	rows,cols,chan = frame.shape
	temp = frame[20:rows-20, 20:cols-20]
	mask = cv.inRange(hsv, lower, ranges)
	
	tempmask =  mask[20:rows-20, 20:cols-20]
	tempres = cv.bitwise_and(temp, temp, mask=tempmask)
	res = cv.copyMakeBorder(tempres, 20,20,20, 20, cv.BORDER_CONSTANT, value=[0,0,0])
	
	# cv.imshow("calibration", res)
	
	res2gray = cv.cvtColor(res, cv.COLOR_BGR2GRAY)
	median = cv.medianBlur(res2gray, 23)

	contours, hierarchy = cv.findContours(median, cv.RETR_TREE, cv.CHAIN_APPROX_SIMPLE)
	if (len(contours) > 0) and (contours is not None) :
		cnt = contours[0]
		(a, b), r = cv.minEnclosingCircle(cnt)
		center = (int(a), int(b))
		radius = int(r)
		cv.circle(frame, center, radius, (0, 128 ,128), 4)

		render_lines(center[0], center[1])
		isDrawing = True
	else:
		if isDrawing:
			List.append([])
			cList.append([])
		isDrawing = False

	# white_arr = np.zeros(frame.shape, np.uint8)
	# white_arr += 255
	
	for i,j in zip(List,cList):
		if j !=[]:
			r,g,b = j[0]
			cv.polylines(frame,[np.array(i, dtype=np.int32)], False, (r,g,b), 2, cv.LINE_AA)
			
			# cv.polylines(white_arr,[np.array(i, dtype=np.int32)], False, (r,g,b), 2, cv.LINE_AA)

	# disp_arr = np.vstack((white_arr, frame))
	return frame


class VideoTransformTrack(MediaStreamTrack):
	"""
	A video stream track that transforms frames from an another track.
	"""

	kind = "video"

	def __init__(self, track):
		super().__init__()  # don't forget this!
		self.track = track

	async def recv(self):
		frame = await self.track.recv()
		npframe = frame.to_ndarray(format="bgr24")
		new_frame = VideoFrame.from_ndarray(canvas(npframe), format="bgr24")
		new_frame.pts = frame.pts
		new_frame.time_base = frame.time_base
		return new_frame


async def index(request):
	content = open(os.path.join(ROOT, "index.html"), "r").read()
	return web.Response(content_type="text/html", text=content)


async def javascript(request):
	content = open(os.path.join(ROOT, "client.js"), "r").read()
	return web.Response(content_type="application/javascript", text=content)


async def offer(request):
	params = await request.json()
	offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

	pc = RTCPeerConnection()
	pc_id = "PeerConnection(%s)" % uuid.uuid4()
	pcs.add(pc)

	def log_info(msg, *args):
		logger.info(pc_id + " " + msg, *args)

	log_info("Created for %s", request.remote)


	@pc.on("iceconnectionstatechange")
	async def on_iceconnectionstatechange():
		log_info("ICE connection state is %s", pc.iceConnectionState)
		if pc.iceConnectionState == "failed":
			await pc.close()
			pcs.discard(pc)

	@pc.on("track")
	def on_track(track):
		log_info("Track %s received", track.kind)
		local_video = VideoTransformTrack(
				track
			)
		pc.addTrack(local_video)

		@track.on("ended")
		async def on_ended():
			log_info("Track %s ended", track.kind)

	# handle offer
	await pc.setRemoteDescription(offer)

	# send answer
	answer = await pc.createAnswer()
	await pc.setLocalDescription(answer)

	return web.Response(
		content_type="application/json",
		text=json.dumps(
			{"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}
		),
	)


async def on_shutdown(app):
	# close peer connections
	coros = [pc.close() for pc in pcs]
	pcs.clear()


def init_func(argv):
	app = web.Application()
	app.on_shutdown.append(on_shutdown)
	app.router.add_get("/", index)
	app.router.add_get("/client.js", javascript)
	app.router.add_post("/offer", offer)
	return app

if __name__ == "__main__":
	# if args.cert_file:
	# 	ssl_context = ssl.SSLContext()
	# 	ssl_context.load_cert_chain(args.cert_file, args.key_file)
	# else:
	# 	ssl_context = None

	app = init_func(None)
	try:
		web.run_app(
			app, access_log=None, host='127.0.0.1', port='8080', ssl_context=None)
	except Exception as e :
		raise e
