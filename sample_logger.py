from MyLoggerHelper import MyLoggerHelper


def main():
    logger = MyLoggerHelper.setup_logger("~/Downloads")
    logger.info("test message!")
    return


if __name__ == "__main__":
    main()
    exit(0)
