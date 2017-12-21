import asyncio
import json
import logging
import os
import time
from datetime import datetime

from aiohttp import web
from jinja2 import Environment, FileSystemLoader

from webapp.www import orm
from webapp.www.config import configs
from webapp.www.coroweb import add_routes, add_static
from webapp.www.handlers import COOKIE_NAME, cookie2user


# 初始化jinja2
def init_jinja2(app, **kw):
    logging.info('init jinja2...')
    # 配置options参数
    options = dict(
        # 自动转义xml/html的特殊字符
        autoescape=kw.get('autoescape', True),
        # 代码块的开始、结束标志
        block_start_string=kw.get('block_start_string', '{%'),
        block_end_string=kw.get('block_end_string', '%}'),
        # 变量的开始、结束标志
        variable_start_string=kw.get('variable_start_string', '{{'),
        variable_end_string=kw.get('variable_end_string', '}}'),
        # 自动加载修改后的模板文件
        auto_reload=kw.get('auto_reload', True)
    )
    # 获取模板文件夹路径
    path = kw.get('path', None)
    if path is None:
        # 模板在templates目录下
        # 当前路径和模板路径拼接
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path: %s' % path)
    # Environment类是jinja2的核心类，用来保存配置、全局对象以及模板文件的路径、过滤器
    # FileSystemLoader(path)加载模板文件
    env = Environment(loader=FileSystemLoader(path), **options)
    # 得到设置的过滤器dict
    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            # 添加过滤器到env的过滤器字典
            env.filters[name] = f
    # 再将jinja2的配置env添加到app中，这样app就能知道如何解析操作模板
    app['__templating__'] = env


# 时间过滤器，将时间（秒）格式化为日期字符串
def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return u'%s分钟前' % (delta // 60)
    if delta < 86400:
        return u'%s小时前' % (delta // 3600)
    if delta < 604800:
        return u'%s天前' % (delta // 86400)
    #
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)


# 输出日志的middleware
async def logger_factory(app, handler):
    async def logger(request):
        logging.info('Request: %s %s' % (request.method, request.path))
        return await handler(request)

    return logger


# 解析cookie的middleware，并将登录用户绑定到request对象上，这样，后续的URL处理函数就可以直接拿到登录用户
async def auth_factory(app, handler):
    async def auth(request):
        logging.info('check user: %s %s' % (request.method, request.path))
        request.__user__ = None
        # 拿到请求的cookie串
        cookie_str = request.cookies.get(COOKIE_NAME)
        if cookie_str:
            user = await cookie2user(cookie_str)
            if user:
                logging.info('set current user: %s' % user.email)
                # 并将登录用户绑定到request对象上，这样，后续的URL处理函数就可以直接拿到当前登录用户信息
                request.__user__ = user
        # 只有登录用户才能创建博客
        if request.path.startswith('/manage/') and (request.__user__ is None):
            return web.HTTPFound('/login')
        return await handler(request)

    return auth


# 处理URL处理函数返回值，构造web.Response对象返回
# handler就是RequestHandler对象
async def response_factory(app, handler):
    async def response(request):
        logging.info('Response handler...')
        # 会去执行RequestHandler的__call__，拿到response，进一步构造web.Response
        r = await handler(request)
        # StreamResponse是所有Response对象的父类，直接返回
        if isinstance(r, web.StreamResponse):
            return r
        if isinstance(r, bytes):
            # 构造http响应内容
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        if isinstance(r, str):
            # 如果是重定向
            if r.startswith('redirect:'):
                # 重定向至目标URL
                return web.HTTPFound(r[9:])
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        if isinstance(r, dict):
            # 在后续构造视图函数返回值时，会加入__template__值，用以选择渲染的模板
            template = r.get('__template__')
            if template is None:
                resp = web.Response(
                    # dumps将对象转换成JSON串，目前是处理rest api的情况
                    # ensure_ascii默认值为True，代表仅输出ascii字符，所以改为False
                    # default=lambda obj: obj.__dict__，定义dumps()把r的对象转换成JSON串的规则，因为默认不知道如何转换
                    body=json.dumps(r, ensure_ascii=False, default=lambda obj: obj.__dict__).encode('utf-8'))
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            else:
                r['__user__'] = request.__user__
                # app['__templating__']获取jinja2中初始化的Environment对象，调用get_template()方法返回Template对象
                # 调用Template对象的render()方法，传入r渲染模板，返回unicode格式字符串，将其用utf-8编码，一气呵成，太炫了
                resp = web.Response(body=app['__templating__'].get_template(template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        # 返回响应码
        if isinstance(r, int) and 100 <= r < 600:
            return web.Response(status=r)
        # 返回了一组响应代码和原因，如：(200, 'OK'), (404, 'Not Found')
        if isinstance(r, tuple) and len(r) == 2:
            status_code, message = r
            if isinstance(status_code, int) and 100 <= status_code < 600:
                return web.Response(status=status_code, text=str(message))
        # 不符合以上情况
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp

    return response


async def init(loop):
    await orm.create_pool(loop=loop, **configs.db)
    app = web.Application(loop=loop, middlewares=[logger_factory, auth_factory, response_factory])
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    add_routes(app, 'handlers')
    add_static(app)
    server = await loop.create_server(app.make_handler(), configs.server.host, configs.server.port)
    logging.info('server started at http://%s:%s' % (configs.server.host, configs.server.port))
    return server


def run_server():
    loop = asyncio.get_event_loop()
    loop.run_until_complete(init(loop))
    loop.run_forever()


# 让你写的脚本模块既可以导入到别的模块中用，另外该模块自己也可执行
# 直接执行app.py时'__main__' == __name__；
# 但把app.py作为模块导入到别的模块，该条件不成立，不会导致该方法重复执行
if '__main__' == __name__:
    run_server()
