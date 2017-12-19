import time

from webapp.www.coroweb import get
from webapp.www.models import User, Blog


@get('/')
async def index():
    users = await User.find_all()
    return {
        # 指定模板名
        '__template__': 'test.html',
        # 传递给模板处理的数据
        'users': users
    }


@get('/main')
def main(request):
    summary = 'Lorem ipsum dolor sit amet, consectetur adipisicing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.'
    blogs = [
        Blog(id='1', name='Test Blog', summary=summary, created_at=time.time() - 120),
        Blog(id='2', name='Something New', summary=summary, created_at=time.time() - 3600),
        Blog(id='3', name='Learn Swift', summary=summary, created_at=time.time() - 7200)
    ]
    return {
        '__template__': 'blogs.html',
        'blogs': blogs
    }


@get('/api/users')
async def api_get_users():
    users = await User.find_all(order_by='created_at desc')
    for u in users:
        u.password = '******'
    return dict(users=users)
