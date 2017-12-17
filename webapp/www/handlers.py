from aiohttp import web

from webapp.www.coroweb import get


@get('/')
async def index(request):
    return '<h1>Awesome</h1>'
