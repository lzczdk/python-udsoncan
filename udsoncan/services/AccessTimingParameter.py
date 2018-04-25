from . import *
from udsoncan.Response import Response
from udsoncan.exceptions import *

class AccessTimingParameter(BaseService):
	_sid = 0x83

	class AccessType(BaseSubfunction):
		__pretty_name__ = 'access type'

		readExtendedTimingParameterSet = 1
		setTimingParametersToDefaultValues = 2
		readCurrentlyActiveTimingParameters = 3
		setTimingParametersToGivenValues = 4

	supported_negative_response = [	Response.Code.SubFunctionNotSupported, 
							Response.Code.IncorrectMessageLegthOrInvalidFormat,
							Response.Code.ConditionsNotCorrect,
							Response.Code.RequestOutOfRange
							]	

	@classmethod
	def make_request(cls, access_type, timing_param_record=None):
		from udsoncan import Request

		ServiceHelper.validate_int(access_type, min=0, max=0x7F, name='Access type')
		
		if timing_param_record is not None and access_type != cls.AccessType.setTimingParametersToGivenValues :
			raise ValueError('timing_param_record can only be set when access_type is setTimingParametersToGivenValues"')

		if timing_param_record is None and access_type == cls.AccessType.setTimingParametersToGivenValues :
			raise ValueError('A timing_param_record must be provided when access_type is "setTimingParametersToGivenValues"')

		if timing_param_record is not None:
			if not isinstance(timing_param_record, bytes):
				raise ValueError("timing_param_record must be a valid bytes objects")

		request = Request(service=cls, subfunction=access_type)
		if timing_param_record is not None:
			request.data += timing_param_record
		
		return request

	@classmethod
	def interpret_response(cls, response):
		if len(response.data) < 1: 	
			raise InvalidResponseException(response, "Response data must be at least 1 byte")

		response.service_data = cls.ResponseData()
		response.service_data.access_type_echo = response.data[0]
		response.service_data.timing_param_record = response.data[1:] if len(response.data) >1 else b''

	class ResponseData(BaseResponseData):
		def __init__(self):
			super().__init__(AccessTimingParameter)
			self.access_type_echo = None
			self.timing_param_record = None
