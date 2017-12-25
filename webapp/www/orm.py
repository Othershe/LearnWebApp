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
        db=kw['database'],
        charset=kw.get('charset', 'utf8'),
        autocommit=kw.get('autocommit', True),
        maxsize=kw.get('maxsize', 10),
        minsize=kw.get('minsize', 1),
        loop=loop
    )


# 封装select功能
async def select(sql, args, size=None):
    log(sql, args)
    async with __pool.get() as conn:
        # 以字典的形式返回查询到的结果[{},{},{}...]
        async with conn.cursor(aiomysql.DictCursor) as cur:
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
        # 开始一个事务
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args)
                affected = cur.rowcount
            if not autocommit:
                # 提交事务
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                # 回滚，即撤销事务里的操作
                await conn.rollback()
            raise
        finally:
            # conn.close()可防止 RuntimeError: Event loop is closed
            conn.close()
        return affected


# 根据要操作的字段个数，生成占位符列表
def create_args_string(count):
    l = []
    for n in range(count):
        l.append('?')
    return ', '.join(l)


# 基类，保存数据库表的字段信息
class Field(object):
    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default


class StringField(Field):
    def __init__(self, name=None, primary_key=False, default=None, column_type='varchar(100)'):
        super().__init__(name, column_type, primary_key, default)


class IntegerField(Field):
    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)


class FloatField(Field):
    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)


class TextField(Field):
    def __init__(self, name=None, primary_key=False, default=None):
        super().__init__(name, 'text', primary_key, default)


class BooleanField(Field):
    def __init__(self, name=None, primary_key=False, default=False):
        super().__init__(name, 'boolean', primary_key, default)


# 定义元类ModelMetaclass（所有的元类都继承自type）
# ModelMetaclass是具体Model的基类，它封装了子类的一些具体操作，继承该元类的子类都具有这些基本操作：
# 该元类的工作主要是为一个数据库表映射成一个封装的类做准备，读取具体子类(user)的映射信息
# 创造类的时候，排除对Model类的修改
# 在子类中查找所有的类属性(attrs)，如果找到属性，就将其保存到__mappings__的dict中，
# 同时从类属性中删除Field(防止实例属性遮住类的同名属性)
# 将数据库表名保存到__table__中
class ModelMetaclass(type):
    # __new__()是在__init__()之前被调用的特殊方法
    # __new__()是用来创建对象并返回的方法
    # 而__init__()只是用来将传入的参数初始化给对象
    # mcs：元类，即当前类的实例
    # name：当前类名
    # bases：当前类的基类
    # attrs：类的所有属性(dict)
    def __new__(mcs, name, bases, attrs):
        # 不处理Model类，因为Model类作为一个抽象的基类存在
        if name == 'Model':
            return type.__new__(mcs, name, bases, attrs)
        table_name = attrs.get('__table__', None)
        logging.info('found model: %s (table: %s)' % (name, table_name))
        # 记录属性名和属性值
        mappings = dict()
        # 记录所有属性名
        fields = []
        # 记录主键
        primary_key = None
        for key, value in attrs.items():
            if isinstance(value, Field):
                logging.info('found mapping: %s --> %s' % (key, value))
                mappings[key] = value
                if value.primary_key:
                    if primary_key:
                        raise AttributeError('Duplicate primary key for field: %s' % key)
                    primary_key = key
                else:
                    fields.append(key)
        if not primary_key:
            raise AttributeError('Primary key not found.')
        for key in mappings.keys():
            # 删除对象里原来的类属性
            attrs.pop(key)
        # 组织一个属性名集合，类似：[`key1`, 'key2']
        escaped_fields = list(map(lambda f: '`%s`' % f, fields))
        # 给attrs添加新的属性（key-value）
        attrs['__mappings__'] = mappings
        attrs['__table__'] = table_name
        attrs['__primary_key__'] = primary_key
        attrs['__fields__'] = fields
        attrs['__select__'] = 'select `%s`, %s from `%s`' % (primary_key, ', '.join(escaped_fields), table_name)
        attrs['__insert__'] = 'insert into `%s` (%s,`%s`) values (%s)' % (
            table_name, ', '.join(escaped_fields), primary_key, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (
            table_name, ', '.join(list(map(lambda f: '`%s`=?' % f, fields))), primary_key)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (table_name, primary_key)
        return type.__new__(mcs, name, bases, attrs)


# 定义数据库Model的基类，封装数据库操作
# 继承dict，则拥有字典的功能d[key]
# 同时重写了__getattr__()、__setattr__()方法，可以通过点号操作属性d.key
class Model(dict, metaclass=ModelMetaclass):
    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError("'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def get_value(self, key):
        return getattr(self, key, None)

    def get_value_default(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default
                logging.error('using default value for %s:%s' % (key, str(value)))
                setattr(self, key, value)
        return value

    # 条件查询
    @classmethod
    async def find_all(cls, where=None, args=None, **kw):
        sql = [cls.__select__]
        if where:
            sql.append('where')
            sql.append(where)
        if args is None:
            args = []
        order_by = kw.get('order_by', None)
        if order_by:
            sql.append('order by')
            sql.append(order_by)
        limit = kw.get('limit', None)
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit, tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)
        return [cls(**r) for r in rs]

    # 根据主键查找
    @classmethod
    async def find(cls, primary_key):
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), primary_key, 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])

    # 保存
    async def save(self):
        # 将属性值组合成list
        args = list(map(self.get_value_default, self.__fields__))
        args.append(self.get_value_default(self.__primary_key__))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.error('failed to insert record: affected rows: %s' % rows)

    # 更新
    async def update(self):
        args = list(map(self.get_value, self.__fields__))
        args.append(self.get_value(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.error('failed to update by primary key: affected rows: %s' % rows)

    # 删除
    async def remove(self):
        args = [self.get_value(self.__primary_key__)]
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.error('failed to remove by primary key: affected rows: %s' % rows)

    @classmethod
    async def find_number(cls, select_field, where=None, args=None):
        # _num_代表别名
        sql = ['select %s _num_ from `%s`' % (select_field, cls.__table__)]
        if where:
            sql.append('where')
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        return rs[0]['_num_']
