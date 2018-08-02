import socket
import queue
import threading
import logging
import binascii
from abc import ABC, abstractmethod

from udsoncan.Request import Request
from udsoncan.Response import Response
from udsoncan.exceptions import TimeoutException

class BaseConnection(ABC):

	def __init__(self, name=None):
		if name is None:
			self.name = 'Connection'
		else:
			self.name = 'Connection[%s]' % (name)

		self.logger = logging.getLogger(self.name)

	def send(self, data):
		"""Sends data to the underlying transport protocol

		:param data: The data or object to send. If a Request or Response is given, the value returned by get_payload() will be sent.
		:type data: bytes, Request, Response

		:returns: None
		"""

		if isinstance(data, Request) or isinstance(data, Response):
			payload = data.get_payload()  
		else :
			payload = data

		self.logger.debug('Sending %d bytes : [%s]' % (len(payload), binascii.hexlify(payload) ))
		self.specific_send(payload)

	def wait_frame(self, timeout=2, exception=False):
		"""Waits for the reception of a frame of data from the underlying transport protocol

		:param timeout: The maximum amount of time to wait before giving up in seconds
		:type timeout: int
		:param exception: Boolean value indicating if this function may return exceptions.
			When ``True``, all exceptions may be raised, including ``TimeoutException``
			When ``False``, all exceptions will be logged as ``DEBUG`` and ``None`` will be returned.
		:type exception: bool

		:returns: Received data
		:rtype: bytes or None
		"""
		try:
			frame = self.specific_wait_frame(timeout=timeout)
		except Exception as e:
			self.logger.debug('No data received: [%s] - %s ' % (e.__class__.__name__, str(e)))

			if exception == True:
				raise
			else:
				frame = None

		if frame is not None:
			self.logger.debug('Received %d bytes : [%s]' % (len(frame), binascii.hexlify(frame) ))
		return frame
	
	def __enter__(self):
		return self

	@abstractmethod
	def specific_send(self, payload):
		"""The implementation of the send method.

		:param payload: Data to send
		:type payload: bytes
		
		:returns: None
		"""
		pass

	@abstractmethod
	def specific_wait_frame(self, timeout=2):
		"""The implementation of the ``wait_frame`` method. 

		:param timeout: The maximum amount of time to wait before giving up
		:type timeout: int
		
		:returns: Received data
		:rtype: bytes or None
		"""
		pass

	@abstractmethod
	def open(self):
		""" Set up the connection object. 

		:returns: None
		"""
		pass

	@abstractmethod
	def close(self):
		""" Close the connection object
		
		:returns: None
		"""
		pass	

	@abstractmethod
	def empty_rxqueue(self):
		""" Empty all unread data in the reception buffer.
		
		:returns: None
		"""
		pass
	
	def __exit__(self, type, value, traceback):
		pass


class SocketConnection(BaseConnection):
	"""
	Sends and receives data through a socket.

	:param sock: The socket to use. This socket must be bound and ready to use. Only ``send()`` and ``recv()`` will be called by this Connection
	:type sock: socket.socket
	:param bufsize: Maximum buffer size of the socket, this value is passed to ``recv()``
	:type bufsize: int
	:param name: This name is included in the logger name so that its output can be redirected. The logger name will be ``Connection[<name>]``
	:type name: string

	"""
	def __init__(self, sock, bufsize=4095, name=None):
		BaseConnection.__init__(self, name)

		self.rxqueue = queue.Queue()
		self.exit_requested = False
		self.opened = False
		self.rxthread = threading.Thread(target=self.rxthread_task)
		self.sock = sock
		self.sock.settimeout(0.1)	# for recv
		self.bufsize=bufsize


	def open(self):
		self.exit_requested = False
		self.rxthread.start()
		self.opened = True
		self.logger.info('Connection opened')
		return self

	def __enter__(self):
		return self

	def __exit__(self, type, value, traceback):
		self.close()

	def is_open(self):
		return self.opened

	def rxthread_task(self):
		while not self.exit_requested:
			try:
				data = self.sock.recv(self.bufsize)
				if data is not None:
					self.rxqueue.put(data)
			except socket.timeout:
				pass
			except Exception:
				self.exit_requested = True


	def close(self):
		self.exit_requested = True
		self.opened = False
		self.logger.info('Connection closed')

	def specific_send(self, payload):
		self.sock.send(payload)

	def specific_wait_frame(self, timeout=2):
		if not self.opened:
			raise RuntimeError("Connection is not open")

		timedout = False
		frame = None
		try:
			frame = self.rxqueue.get(block=True, timeout=timeout)

		except queue.Empty:
			timedout = True
			
		if timedout:
			raise TimeoutException("Did not received frame in time (timeout=%s sec)" % timeout)

		return frame

	def empty_rxqueue(self):
		while not self.rxqueue.empty():
			self.rxqueue.get()


class IsoTPConnection(BaseConnection):
	"""
	Sends and receives data through an ISO-TP socket. Makes cleaner code than SocketConnection but offers no additional functionality.
	The `isotp module <https://github.com/pylessard/python-can-isotp>`_ must be installed in order to use this connection

	:param interface: The can interface to use (example: `can0`)
	:type interface: string
	:param rxid: The reception CAN id
	:type rxid: int 
	:param txid: The transmission CAN id
	:type txid: int
	:param name: This name is included in the logger name so that its output can be redirected. The logger name will be ``Connection[<name>]``
	:type name: string
	:param tpsock: An optional ISO-TP socket to use instead of creating one.
	:type tpsock: isotp.socket

	"""
	def __init__(self, interface, rxid, txid, name=None, tpsock=None):
		import isotp
		BaseConnection.__init__(self, name)

		self.interface=interface
		self.rxid=rxid
		self.txid=txid
		self.rxqueue = queue.Queue()
		self.exit_requested = False
		self.opened = False

		self.rxthread = threading.Thread(target=self.rxthread_task)
		self.tpsock = isotp.socket(timeout=0.1) if tpsock is None else tpsock


	def open(self):
		self.tpsock.bind(self.interface, rxid=self.rxid, txid=self.txid)
		self.exit_requested = False
		self.rxthread.start()
		self.opened = True
		self.logger.info('Connection opened')
		return self

	def __enter__(self):
		return self

	def __exit__(self, type, value, traceback):
		self.close()

	def is_open(self):
		return self.tpsock.bound

	def rxthread_task(self):
		while not self.exit_requested:
			try:
				data = self.tpsock.recv()
				if data is not None:
					self.rxqueue.put(data)
			except socket.timeout:
				pass
			except Exception:
				self.exit_requested = True


	def close(self):
		self.exit_requested = True
		self.tpsock.close()
		self.opened = False
		self.logger.info('Connection closed')

	def specific_send(self, payload):
		self.tpsock.send(payload)

	def specific_wait_frame(self, timeout=2):
		if not self.opened:
			raise RuntimeError("Connection is not open")

		timedout = False
		frame = None
		try:
			frame = self.rxqueue.get(block=True, timeout=timeout)

		except queue.Empty:
			timedout = True
			
		if timedout:
			raise TimeoutException("Did not received ISOTP frame in time (timeout=%s sec)" % timeout)

		return frame

	def empty_rxqueue(self):
		while not self.rxqueue.empty():
			self.rxqueue.get()


class QueueConnection(BaseConnection):
	"""
	Sends and receives data using 2 Python native queues.

	- ``MyConnection.fromuserqueue`` : Data read from this queue when ``wait_frame`` is called
	- ``MyConnection.touserqueue`` : Data written to this queue when ``send`` is called

	:param mtu: Optional maximum frame size. Messages will be truncated to this size
	:type mtu: int
	:param name: This name is included in the logger name so that its output can be redirected. The logger name will be ``Connection[<name>]``
	:type name: string

	"""
	def __init__(self, name=None, mtu=4095):
		BaseConnection.__init__(self, name)

		self.fromuserqueue = queue.Queue()	# Client reads from this queue. Other end is simulated
		self.touserqueue = queue.Queue()	# Client writes to this queue. Other end is simulated
		self.opened = False
		self.mtu = mtu

	def open(self):
		self.opened = True
		self.logger.info('Connection opened')
		return self

	def __enter__(self):
		return self

	def __exit__(self, type, value, traceback):
		self.close()

	def is_open(self):
		return self.opened 

	def close(self):
		self.empty_rxqueue()
		self.empty_txqueue()
		self.opened = False
		self.logger.info('Connection closed')	

	def specific_send(self, payload):
		if self.mtu is not None:
			if len(payload) > self.mtu:
				self.logger.warning("Truncating payload to be set to a length of %d" % (self.mtu))
				payload = payload[0:self.mtu]

		self.touserqueue.put(payload)

	def specific_wait_frame(self, timeout=2):
		if not self.opened:
			raise RuntimeException("Connection is not open")

		timedout = False
		frame = None
		try:
			frame = self.fromuserqueue.get(block=True, timeout=timeout)
		except queue.Empty:
			timedout = True
			
		if timedout:
			raise TimeoutException("Did not receive frame from user queue in time (timeout=%s sec)" % timeout)
		
		if self.mtu is not None:
			if frame is not None and len(frame) > self.mtu:
				self.logger.warning("Truncating received payload to a length of %d" % (self.mtu))
				frame = frame[0:self.mtu]

		return frame

	def empty_rxqueue(self):
		while not self.fromuserqueue.empty():
			self.fromuserqueue.get()

	def empty_txqueue(self):
		while not self.touserqueue.empty():
			self.touserqueue.get()

