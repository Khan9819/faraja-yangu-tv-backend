from rest_framework.response import Response

def success_response(data=None, message='Success'):
    return Response({'success': True, 'message': message, 'data': data})

def error_response(message='Error', code=400, errors=None):
    response = {'success': False, 'message': message}
    if errors is not None:
        response['errors'] = errors
    return Response(response, status=code)
