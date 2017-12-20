import functools
import asyncio
import inspect
import logging
import os
from urllib import parse
from aiohttp import web
from webapp.www.apis import APIError


# 参考 http://blog.csdn.net/jyk920902/article/details/78262416

# URL处理函数的装饰器，存储请求方式、URL
def request(path, *, method):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)

        wrapper.__method__ = method
        wrapper.__route__ = path
        return wrapper

    return decorator


# 利用偏函数，得到GET、POST类型的装饰器
get = functools.partial(request, method='GET')
post = functools.partial(request, method='POST')

"""
https://docs.python.org/3/library/inspect.html#inspect.Signature
inspect.Parameter.kind 类型：
POSITIONAL_ONLY          位置参数
KEYWORD_ONLY             命名关键字参数
VAR_POSITIONAL           可选参数 *args
VAR_KEYWORD              关键字参数 **kw
POSITIONAL_OR_KEYWORD    位置或必选参数
"""


# 获取函数的无默认值的命名关键字参数名
def get_required_kw_args(fn):
    args = []
    # 获取函数fn的参数列表
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        # 函数fn有命名关键字参数，并且默认值为空，则记录参数名
        if param.kind == inspect.Parameter.KEYWORD_ONLY and param.default == inspect.Parameter.empty:
            args.append(name)
    return tuple(args)


# 获取函数的命名关键字参数名
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)


# 函数是否有命名关键字参数
def has_named_kw_args(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            return True


# 函数是否有关键字参数
def has_var_kw_arg(fn):
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            return True


# 函数是否有request参数
def has_request_arg(fn):
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
        if found and (param.kind != inspect.Parameter.VAR_POSITIONAL
                      and param.kind != inspect.Parameter.KEYWORD_ONLY
                      and param.kind != inspect.Parameter.VAR_KEYWORD):
            raise ValueError(
                'request parameter must be the last named parameter in function: %s%s' % (fn.__name__, str(sig)))
    return found


# 初始化RequestHandler时执行__init__，分析URL处理函数需要接受的参数信息，并保存起来
# 浏览器发起请求后执行__call__，取出request中携带的参数，和初始化时得到的信息检验比对，得到最终的request参数
# 最后执行URL处理函数，使用最终的request参数
# 断点后发现调起__call__的地方在response_factory里边
class RequestHandler(object):
    def __init__(self, app, fn):
        self._app = app
        # URL处理函数
        self._func = fn
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_args = has_named_kw_args(fn)
        self._named_kw_args = get_named_kw_args(fn)
        self._required_kw_args = get_required_kw_args(fn)

    async def __call__(self, request):
        kw = None
        # 如果URL处理函数有关键字参数 或者 命名关键字参数 或者 无默认值的命名关键字参数
        if self._has_var_kw_arg or self._has_named_kw_args or self._required_kw_args:
            # POST请求的情况
            if request.method == 'POST':
                # 缺少content_type
                if not request.content_type:
                    return web.HTTPBadRequest('Missing Content-Type.')
                # 转小写以方法处理
                ct = request.content_type.lower()
                # json格式请求
                if ct.startswith('application/json'):
                    # 拿到json参数
                    params = await request.json()
                    request.json()
                    # request.json()应该返回dict对象
                    if not isinstance(params, dict):
                        return web.HTTPBadRequest('JSON body must be object.')
                    kw = params
                # 表单形式的请求
                elif ct.startswith('application/x-www-form-urlencoded') or ct.startswith('multipart/form-data'):
                    # 拿到表单参数，组织一个dict
                    params = await request.post()
                    kw = dict(**params)
                else:
                    # 不支持的请求参数类型
                    return web.HTTPBadRequest('Unsupported Content-Type: %s' % request.content_type)
            # GET请求的情况
            if request.method == 'GET':
                # 取出?后的参数，/?name=tom&age=18
                # qs:name=tom&age=18
                qs = request.query_string
                if qs:
                    kw = dict()
                    # True:不忽略空格
                    # parse.parse_qs(qs, True)-->{'name': ['tom'], 'age': ['18']}
                    for k, v in parse.parse_qs(qs, True).items():
                        kw[k] = v[0]
        if kw is None:
            # 原url:/a/{id}，映射成/a/{1234}
            # match_info：dict(id=1234)
            kw = dict(**request.match_info)
        else:
            # 如果没有 关键字参数 只有 命名关键字参数
            if not self._has_var_kw_arg and self._named_kw_args:
                copy = dict()
                # 去除原参数中的非命名关键字参数
                for name in self._named_kw_args:
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            # check named arg:
            for k, v in request.match_info.items():
                # 检查kw中的参数是否有和match_info中重复的
                if k in kw:
                    logging.warning('Duplicate arg name in named arg and kw args: %s' % k)
                kw[k] = v
        # 记录request参数
        if self._has_request_arg:
            kw['request'] = request
        # URL处理数有无默认值的命名关键字参数
        if self._required_kw_args:
            for name in self._required_kw_args:
                # 但未传入对应参数，则报错
                if name not in kw:
                    return web.HTTPBadRequest('Missing argument: %s' % name)
        # 到这里完成了request中参数的检验
        logging.info('call with args: %s' % str(kw))
        try:
            # 执行URL处理函数
            r = await self._func(**kw)
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)


# 注册静态资源如css、js，这里只要是添加前端框架的资源（放在static目录下）
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    logging.info('add static %s => %s' % ('/static/', path))


# 注册单个URL处理函数
def add_route(app, fn):
    # URL处理函数fn的请求方式
    method = getattr(fn, '__method__', None)
    # fn的URL
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in %s.' % str(fn))
    # URL处理函数不是协程 并且 不是生成器
    if not asyncio.iscoroutinefunction(fn) and not inspect.isgeneratorfunction(fn):
        # 将URL处理函数转成协程
        fn = asyncio.coroutine(fn)
    logging.info(
        'add route %s %s => %s(%s)' % (method, path, fn.__name__, ', '.join(inspect.signature(fn).parameters.keys())))
    # 注册URL处理函数
    app.router.add_route(method, path, RequestHandler(app, fn))


# 批量注册模块中的URL处理函数
def add_routes(app, module_name):
    # 从字符串右边开始查找，返回字符下标，找不到返回-1
    n = module_name.rfind('.')
    if n == (-1):
        # 函数__import__作用类似import，('my_module',globals(),locals(),['a','b'], 0) ,等价于from my_module import a, b
        # import module_name
        mod = __import__(module_name, globals(), locals())
    else:
        # 截取module_name，或者最终导入的module的name
        name = module_name[n + 1:]
        # __import__(module_name[:n], globals(), locals(), [name]) ==> from module_name[:n] import name
        mod = getattr(__import__(module_name[:n], globals(), locals(), [name]), name)
    # 迭代mod模块中所有的类，实例及函数等对象, str形式
    for attr in dir(mod):
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr)
        # 如果是我们的URL处理函数
        if callable(fn):
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)
