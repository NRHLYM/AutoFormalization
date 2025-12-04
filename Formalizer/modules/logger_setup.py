"""
Formalizer/modules/logger_setup.py
配置日志系统：
- Console (终端): 只显示 INFO 及以上级别 (清爽)
- File (文件): 显示 DEBUG 及以上级别 (详尽，包含代码和 Prompt)
"""
import logging
import sys
import os


def setup_logging(log_file_path):
    # 1. 获取根日志记录器
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)  # 根记录器捕捉所有信息

    # 清除旧的 handler (防止重复打印)
    if logger.hasHandlers():
        logger.handlers.clear()

    # 2. 文件 Handler (写入所有细节：DEBUG)
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    # 文件里带上时间戳，方便排查
    file_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # 3. 终端 Handler (只显示主要进度：INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    # 终端只需要显示纯消息，不需要时间戳
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger