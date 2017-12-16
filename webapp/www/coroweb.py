import functools
import asyncio
import inspect
from aiohttp import web
from webapp.www.apis import APIError


# GET、POST等请求函数的URL处理的装饰器函数
def request(path, *, method):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)

        wrapper.__method__ = method
        wrapper.__route__ = path
        return wrapper

    return decorator


# 利用偏函数，提前确定request函数的method参数
get = functools.partial(request, method='GET')
post = functools.partial(request, method='POST')


# RequestHandler目的就是从URL函数中分析其需要接收的参数，从request中获取必要的参数，
# 调用URL函数，然后把结果转换为web.Response对象，这样，就完全符合aiohttp框架的要求：
class RequestHandler(object):
    def __init__(self, fn):
        self._func = asyncio.coroutine(fn)

    async def __call__(self, request):
        # 获取参数列表
        request_args = inspect.signature(self._func).parameters
        # 获取从 GET\POST 传入的参数值，如果函数参数表有这个参数名就加入字典,例如/?page=2、api的json或者是网页中from
        kw = {arg: value for arg, value in request().__data__.item() if arg in request_args}
        # 获取match_info的参数值，例如@get('/blog/{id}')之类的参数值
        kw.update(dict(**request.match_info))
        # 3、如果有request参数，也要加入字典，有时需要验证用户信息就需要获取request里面的数据
        if 'request' in request_args:
            kw['request'] = request

        # 检查参数合法性
        for arg, value in request_args.items():
            # request参数不能为可变长参数
            if arg == 'request' and value.kind in (arg.VAR_POSITIONAL, arg.VAR_KEYWORD):
                return web.HTTPBadRequest('request parameter cannot be the var argument.')
            if value.kind not in (arg.VAR_POSITIONAL, arg.VAR_KEYWORD):
                # 如果没有默认值
                if value.default == value.empty and value.name not in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % arg.name)
        try:
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)
