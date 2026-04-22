import time


def generate_load(requests: int = 10) -> None:
    for i in range(requests):
        print(f"Sending request {i + 1}/{requests}")
        time.sleep(0.1)


if __name__ == "__main__":
    generate_load()
