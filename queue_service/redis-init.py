import redis


def init_redis(host: str = 'redis', port: int = 6379) -> None:
    client = redis.Redis(host=host, port=port)
    client.ping()


if __name__ == '__main__':
    init_redis()
