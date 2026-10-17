import argparse
import sys
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video")
    parser.add_argument("--smoke-screenshot")
    args = parser.parse_args()
    from PyQt5.QtCore import QLockFile, Qt
    from PyQt5.QtWidgets import QApplication, QMessageBox
    from .app import MainWindow
    from .project import DATA

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("篮球剪辑大师")
    app.setOrganizationName("BasketballMaster")
    DATA.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(DATA / "desktop.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "篮球剪辑大师", "软件已经打开，请在任务栏中切换到现有窗口。")
        return 0

    def exception_hook(kind, value, tb):
        DATA.mkdir(parents=True, exist_ok=True)
        with (DATA / "errors.log").open("a", encoding="utf-8") as log:
            traceback.print_exception(kind, value, tb, file=log)
        QMessageBox.critical(None, "操作未完成", str(value))

    sys.excepthook = exception_hook
    window = MainWindow(args.video)
    window.show()
    if args.smoke_screenshot:
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(1500, lambda: (window.grab().save(args.smoke_screenshot), app.quit()))
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
