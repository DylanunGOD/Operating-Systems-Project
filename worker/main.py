from shared.logger import get_logger

logger = get_logger(__name__)


def run_worker() -> None:
    logger.info('Worker listener started')


if __name__ == '__main__':
    run_worker()
