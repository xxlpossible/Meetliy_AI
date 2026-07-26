import pickle

import redis
from loguru import logger
from redis import ConnectionPool, RedisCluster
from redis.backoff import ExponentialBackoff
from redis.cluster import ClusterNode
from redis.retry import Retry
from redis.sentinel import Sentinel

from settings import settings


class RedisClient:
    def __init__(self, url=None, max_connections=100):
        # 集群模式 和 哨兵模式
        if isinstance(settings.redis_url, dict):
            redis_conf = dict(settings.redis_url)
            # pop 移除并返回字典中指定键（key）对应的值 如果该键不存在，可以返回一个默认值
            mode = redis_conf.pop('mode', 'sentinel')
            # 集群模式
            if mode == 'cluster':
                cluster_url = ''
                if 'startup_nodes' in redis_conf:
                    first_node = redis_conf['startup_nodes'][0]
                    cluster_url = f'redis://{first_node["host"]}:{first_node["port"]}'
                    redis_conf['startup_nodes'] = [
                        ClusterNode(node.get('host'), node.get('port'))
                        for node in redis_conf['startup_nodes']
                    ]
                self.connection = RedisCluster.from_url(cluster_url, **redis_conf,
                                                        retry=Retry(ExponentialBackoff(), 6),
                                                        cluster_error_retry_attempts=1)
                return
            # 未进入集群模式的代码 进入哨兵模式
            hosts = [eval(x) for x in redis_conf.pop('sentinel_hosts')]
            password = redis_conf.pop('sentinel_password')
            master = redis_conf.pop('sentinel_master')
            sentinel = Sentinel(sentinels=hosts, socket_timeout=0.1, password=password)
            # 获取主节点的连接
            self.connection = sentinel.master_for(master, socket_timeout=0.1, **redis_conf)

        else:
            # 单机模式
            if url is None or url == '':
                url = settings.redis_url
            self.pool = ConnectionPool.from_url(url, max_connections=max_connections)
            self.connection = redis.StrictRedis(connection_pool=self.pool)

    def set(self, key, value, expiration=3600):
        try:
            if pickled := pickle.dumps(value):
                self.cluster_nodes(key)
                if expiration > 0:
                    result = self.connection.setex(key, expiration, pickled)
                else:
                    result = self.connection.set(key, pickled)
                if not result:
                    raise ValueError('RedisCache could not set the value.')
            else:
                logger.error('pickle error, value={}', value)
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc
        finally:
            self.close()

    def set_nx(self, key, value, expiration=3600):
        try:
            if pickled := pickle.dumps(value):
                self.cluster_nodes(key)
                result = self.connection.setnx(key, pickled)
                self.connection.expire(key, expiration)
                if not result:
                    return False
                return True
        except TypeError as exc:
            raise TypeError('RedisCache only accepts values that can be pickled. ') from exc
        finally:
            self.close()

    def h_set_key(self, name, key, value, expiration=3600):
        try:
            self.cluster_nodes(key)
            r = self.connection.hset(name, key, value)
            if expiration:
                self.connection.expire(name, expiration)
            return r
        finally:
            self.close()

    def h_set(self, name, map: dict, expiration=3600):
        try:
            self.cluster_nodes(name)
            r = self.connection.hset(name, mapping=map)
            if expiration:
                self.connection.expire(name, expiration)
            return r
        finally:
            self.close()

    def h_get(self, name, key):
        try:
            self.cluster_nodes(name)
            return self.connection.hget(name, key)
        finally:
            self.close()

    def get(self, key):
        try:
            self.cluster_nodes(key)
            value = self.connection.get(key)
            return pickle.loads(value) if value else None
        finally:
            self.close()

    def delete(self, key):
        try:
            self.cluster_nodes(key)
            return self.connection.delete(key)
        finally:
            self.close()

    def exists(self, key):
        try:
            self.cluster_nodes(key)
            return self.connection.exists(key)
        finally:
            self.close()

    def close(self):
        self.connection.close()

    def __contains__(self, key):
        """Check if the key is in the cache."""
        self.cluster_nodes(key)
        return False if key is None else self.connection.exists(key)

    def __getitem__(self, key):
        """Retrieve an item from the cache using the square bracket notation."""
        self.cluster_nodes(key)
        return self.connection.get(key)

    def __setitem__(self, key, value):
        """Add an item to the cache using the square bracket notation."""
        self.cluster_nodes(key)
        self.connection.set(key, value)

    def __delitem__(self, key):
        """Remove an item from the cache using the square bracket notation."""
        self.cluster_nodes(key)
        self.connection.delete(key)

    def cluster_nodes(self, key):
        if isinstance(self.connection,
                      RedisCluster) and self.connection.get_default_node() is None:
            target = self.connection.get_node_from_key(key)
            self.connection.set_default_node(target)

    def r_push(self, key, value, expiration=3600):
        try:
            self.cluster_nodes(key)
            ret = self.connection.rpush(key, value)
            if expiration:
                self.expire_key(key, expiration)
            return ret
        finally:
            self.close()

    def expire_key(self, key, expiration: int):
        try:
            self.cluster_nodes(key)
            self.connection.expire(key, expiration)
        finally:
            self.close()

    def l_pop(self, key, count: int | None = None):
        try:
            self.cluster_nodes(key)
            return self.connection.lpop(key, count)
        finally:
            self.close()

    def l_range(self, key):
        try:
            self.cluster_nodes(key)
            return self.connection.lrange(key, 0, -1)
        finally:
            self.close()

    def r_push_str(self, key: str, value: str, expiration: int = 7200):
        """向 Redis List 右侧推送字符串值（不经过 pickle 序列化）。"""
        try:
            self.cluster_nodes(key)
            ret = self.connection.rpush(key, value)
            if expiration:
                self.connection.expire(key, expiration)
            return ret
        finally:
            self.close()

    def l_range_str(self, key: str) -> list:
        """获取 Redis List 全部元素（返回原始字符串/bytes 列表）。"""
        try:
            self.cluster_nodes(key)
            return self.connection.lrange(key, 0, -1)
        finally:
            self.close()

    def get_keys_by_prefix(self, prefix: str):
        try:
            self.cluster_nodes(prefix)
            matching_keys = self.connection.scan_iter(f"{prefix}*")  # 获取所有匹配的 key
            result = {key: pickle.loads(self.connection.get(key)) for key in matching_keys if self.connection.get(key)}
            return result
        finally:
            self.close()


redis_client = RedisClient(settings.redis_url)
