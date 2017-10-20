from udsoncan import Response, Request, services, DidCodec
from udsoncan.exceptions import *
from udsoncan.configs import default_client_config
import struct
import logging

class Client:
	def __init__(self, conn, config=default_client_config, request_timeout = 1, heartbeat  = None):
		self.conn = conn
		self.request_timeout = request_timeout
		self.config = config
		self.heartbeat = heartbeat
		self.logger = logging.getLogger("UdsClient")

	def __enter__(self):
		self.open()
		return self
	
	def __exit__(self, type, value, traceback):
		self.close()

	def open(self):
		if not self.conn.is_open():
			self.conn.open()

	def close(self):
		self.conn.close()

## 	DiagnosticSessionControl
	def change_session(self, newsession):
		service = services.DiagnosticSessionControl(newsession)
		req = Request(service)
		#No service params
		return self.send_request(req)

##  SecurityAccess
	def request_key(self, level):
		service = services.SecurityAccess(level, mode=services.SecurityAccess.Mode.RequestSeed)
		req = Request(service)
		return self.send_request(req)

	def send_key(self, level, key):
		service = services.SecurityAccess(level, mode=services.SecurityAccess.Mode.SendKey)
		req = Request(service)
		req.data = key
		return self.send_request(req)

	def unlock_security_access(self, level):
		if not callable(self.config['security_algo']):
			raise NotImplementedError("Client configuration does not provide a security algorithm")
		
		request_seed_response = self.request_key(level)
		seed = request_seed_response.data
		key = self.config['security_algo'].__call__(seed)
		self.send_key(level, key)

	def send_tester_present(self, suppress_positive_response=False):
		req = Request(services.TesterPresent(), suppress_positive_response=suppress_positive_response)
		self.send_request(req)


	def check_did_config(self, didlist):
		didlist = [didlist] if not isinstance(didlist, list) else didlist
		if not 'data_identifiers' in self.config or  not isinstance(self.config['data_identifiers'], dict):
			raise AttributeError('Configuration does not contains a valid data identifier description.')
		didconfig = self.config['data_identifiers']

		for did in didlist:
			if did not in didconfig:
				raise LookupError('Actual data identifier configuration contains no definition for data identifier %d' % did)

		return didconfig


	def read_data_by_identifier(self, dids, output_fmt='dict', force_collection=False):
		service = services.ReadDataByIdentifier(dids)
		self.logger.info("Reading data identifier %s", dids)
		req = Request(service)
		didlist = [service.dids] if not isinstance(service.dids, list) else service.dids

		didconfig = self.check_did_config(didlist)
		req.data = struct.pack('>'+'H'*len(didlist), *didlist)
		response = self.send_request(req)

		if output_fmt in ['list']:
			values = []
		elif output_fmt == 'dict':
			values = {}
		else:
			raise ValueError("Output format cannot be %s. Use default|list|dict" % output_fmt)

		offset = 0
		for did in didlist:
			codec = DidCodec.from_config(didconfig[did])
			subpayload = response.data[offset:offset+len(codec)]
			offset += len(codec)
			val = codec.decode(subpayload)

			if output_fmt in ['list']:
				values.append(val)
			elif output_fmt == 'dict':
				values[did] = val

		if len(values) == 1 and not force_collection:
			if isinstance(values, list):
				values = values[0]
			elif isinstance(values, dict):
				values = values[next(iter(values))]

		return values

	def write_data_by_identifier(self, did, value):
		service = services.WriteDataByIdentifier(did)
		self.logger.info("Reading data identifier %s", did)
		req = Request(service)
		
		didconfig = self.check_did_config(did)
		req.data = struct.pack('>H', service.did)
		codec = DidCodec.from_config(didconfig[did])
		req.data += codec.encode(value)
		response = self.send_request(req)
		return response

	def ecu_reset(self, resettype, powerdowntime=None):
		service = services.ECUReset(resettype, powerdowntime)
		self.logger.info("Requesting ECU reset of type 0x%02x" % (resettype))
		req = Request(service)
		if resettype == services.ECUReset.enableRapidPowerShutDown:
			req.data =struct.pack('B', service.powerdowntime)
		return self.send_request(req)

		
	def send_request(self, request, timeout=-1, validate_response=True):
		if timeout is not None and timeout < 0:
			timeout = self.request_timeout
		self.conn.empty_rxqueue()
		self.logger.debug("Sending request to server")
		self.conn.send(request)

		if not request.suppress_positive_response:
			self.logger.debug("Waiting for server response")
			payload = self.conn.wait_frame(timeout=timeout, exception=True)
			response = Response.from_payload(payload)
			self.logger.info("Response received from server")
			
			if not response.valid:
				self.logger.error("Invalid response gotten by server")
				if validate_response:
					raise InvalidResponseException(response)

			if response.service.response_id() != request.service.response_id():
				msg = "Response gotten from server has a service ID different than the one of the request. Received=%s, Expected=%s" % (response.service.response_id() , request.service.response_id() )
				self.logger.error(msg)
				raise UnexpectedResponseException(response, details=msg)
			if not response.positive:
				self.logger.warning("Server responded with Negative response %s" % response.code_name)
				if not request.service.is_supported_negative_response(response.code):
					self.logger.warning("Given response (%s) is not a supported negative response code according to UDS standard." % response.code_name)	
				if validate_response:
					raise NegativeResponseException(response)

			return response
