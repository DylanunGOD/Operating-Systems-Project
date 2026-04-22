from shared.logger import get_logger

logger = get_logger(__name__)


def run_scheduler() -> None:
    logger.info('Coordinator scheduler started')


if __name__ == '__main__':
    run_scheduler()
