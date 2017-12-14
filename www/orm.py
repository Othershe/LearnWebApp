import logging
import aiomysql


# 打印SQL语句
def log(sql, args=()):
    logging.info('SQL: %s' % sql)


# 创建一个全局的连接池，每个HTTP请求都可以从连接池中直接获取数据库连接
# 使用连接池的好处是不必频繁地打开和关闭数据库连接，而是能复用就尽量复用
async def create_pool(loop, **kw):
    logging.info("create a database connection pool...")
    global __pool
    __pool = await aiomysql.create_pool(
        host=kw.get('host', 'localhost'),
        port=kw.get('port', 3306),
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset', 'utf-8'),
        autocommit=kw.get('autocommit', True),
        maxsize=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
        loop=loop
    )


# 封装select功能
async def select(sql, args, size=None):
    log(sql, args)
    async with  __pool.get() as conn:
        async with  conn.cursor(aiomysql.DictCursor) as cur:
            # SQL语句的占位符为?，MySQL的占位符为%s，需要替换
            await cur.execute(sql.replace('?', '%s'), args)
            if size:
                rs = await cur.fetchmany(size)
            else:
                rs = await cur.fetchall()
            logging.info('rows returned:%s' % len(rs))
            return rs


# 封装insert、delete、update
async def execute(sql, args, autocommit=True):
    log(sql, args)
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', "%s"), args)
                affected = cur.rowcount
            if not autocommit:
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()
            raise
        finally:
            # conn.close()可防止 RuntimeError: Event loop is closed
            conn.close()
        return affected
