# tests/common/scan/test_pool_watchdog.py
from __future__ import annotations
import pytest
import time
import threading
from unittest.mock import Mock
from modules.common.scan.pool_watchdog import PoolWatchdog

@pytest.fixture
def mock_future():
    future = Mock()
    future.done = Mock(return_value=False)
    return future

@pytest.fixture
def mock_callback():
    return Mock()

@pytest.fixture
def sample_batch():
    return [{"id": 1, "name": "dev1"}, {"id": 2, "name": "dev2"}]


def test_init_sets_empty_tracked(mock_logger):
    watchdog = PoolWatchdog(mock_logger)
    assert watchdog._tracked == []
    assert watchdog._logger is mock_logger


def test_track_adds_task_with_correct_deadline(
        mock_logger, mock_future, mock_callback, sample_batch, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(mock_future, sample_batch, 1.0, mock_callback, "TestGroup")
    
    assert len(watchdog._tracked) == 1
    deadline, future, batch, callback, group = watchdog._tracked[0]
    assert deadline == 1001.0
    assert future is mock_future
    assert batch is sample_batch
    assert callback is mock_callback
    assert group == "TestGroup"


def test_track_handles_zero_ttl(
        mock_logger, mock_future, mock_callback, sample_batch, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(mock_future, sample_batch, 0.0, mock_callback)
    
    deadline, _, _, _, _ = watchdog._tracked[0]
    assert deadline == 1000.0


def test_track_handles_negative_ttl(
        mock_logger, mock_future, mock_callback, sample_batch, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(mock_future, sample_batch, -1.0, mock_callback)
    
    deadline, _, _, _, _ = watchdog._tracked[0]
    assert deadline == 999.0


def test_track_default_group_name(
        mock_logger, mock_future, mock_callback, sample_batch):
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(mock_future, sample_batch, 1.0, mock_callback)
    # group_name not specified
    
    _, _, _, _, group = watchdog._tracked[0]
    assert group == "UnknownScanner"


def test_track_thread_safety(
        mock_logger, mock_future, mock_callback, sample_batch):
    watchdog = PoolWatchdog(mock_logger)
    threads = []
    
    def add_task():
        watchdog.track(mock_future, sample_batch, 1.0, mock_callback)
    
    for _ in range(10):
        t = threading.Thread(target=add_task)
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    assert len(watchdog._tracked) == 10


def test_check_and_recover_removes_completed_task(
        mock_logger, mock_future, mock_callback, sample_batch):
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(mock_future, sample_batch, 10.0, mock_callback)
    
    # all tasks is done
    mock_future.done.return_value = True
    
    watchdog.check_and_recover()
    
    assert len(watchdog._tracked) == 0
    mock_callback.assert_not_called()


def test_check_and_recover_keeps_active_task(
        mock_logger, mock_future, mock_callback, sample_batch, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(mock_future, sample_batch, 10.0, mock_callback) # deadline = 1010.0
    
    # time = 1000.0
    mock_future.done.return_value = False
    
    watchdog.check_and_recover()
    
    assert len(watchdog._tracked) == 1
    mock_callback.assert_not_called()


def test_check_and_recover_triggers_timeout(
        mock_logger, mock_future, mock_callback, sample_batch, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(mock_future, sample_batch, 10.0, mock_callback)
    # deadline = 1010.0
    
    monkeypatch.setattr(time, "time", lambda: 1011.0) # time = 1011.0

    mock_future.done.return_value = False
    
    watchdog.check_and_recover()
    
    assert len(watchdog._tracked) == 0
    mock_callback.assert_called_once_with(sample_batch)
    log = "WTCH_DOG: one thread dead in group 'UnknownScanner'"
    mock_logger.wrn.assert_called_once_with(log)


def test_check_and_recover_logs_error_on_callback_exception(
        mock_logger, mock_future, mock_callback, sample_batch, monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(mock_future, sample_batch, 10.0, mock_callback, "TestGroup")
    # deadline = 1010.0
    
    monkeypatch.setattr(time, "time", lambda: 1011.0) # time = 1011.0

    mock_future.done.return_value = False
    mock_callback.side_effect = ValueError("test error")
    
    watchdog.check_and_recover()
    
    assert len(watchdog._tracked) == 0
    mock_callback.assert_called_once_with(sample_batch)
    log = "WTCH_DOG error in group 'TestGroup': test error"
    mock_logger.err.assert_called_once_with(log)



def test_check_recover_handles_mixed_tasks(
        mock_logger, sample_batch, monkeypatch):
    
    future1 = Mock()
    future1.done = Mock(return_value=True)
    
    future2 = Mock()
    future2.done = Mock(return_value=False)
    
    future3 = Mock()
    future3.done = Mock(return_value=False)
    
    cb1 = Mock()
    cb2 = Mock()
    cb3 = Mock()
    
    monkeypatch.setattr(time, "time", lambda: 1000.0)
    watchdog = PoolWatchdog(mock_logger)
    watchdog.track(future1, sample_batch, 9.0, cb1, "TestGroup1") # deadline = 1009.0
    watchdog.track(future2, sample_batch, 9.0, cb2, "TestGroup2") # deadline = 1009.0
    watchdog.track(future3, sample_batch, 1.0, cb3, "TestGroup3") # deadline = 1001.0

    monkeypatch.setattr(time, "time", lambda: 1005.0) # time = 1005.0
    
    watchdog.check_and_recover()
    
    assert len(watchdog._tracked) == 1
    _, _, _, _, group = watchdog._tracked[0]
    assert group == "TestGroup2"
    cb1.assert_not_called()
    cb2.assert_not_called()
    cb3.assert_called_once_with(sample_batch)
    log = "WTCH_DOG: one thread dead in group 'TestGroup3'"
    mock_logger.wrn.assert_called_once_with(log)


def test_check_recover_with_empty_tracked(mock_logger):
    watchdog = PoolWatchdog(mock_logger)
    watchdog.check_and_recover()
    
    assert watchdog._tracked == []
    mock_logger.wrn.assert_not_called()
    mock_logger.err.assert_not_called()


def test_check_and_recover_thread_safety(
        mock_logger, mock_future, mock_callback, sample_batch):
    watchdog = PoolWatchdog(mock_logger)
    threads = []
    
    def add_task():
        watchdog.track(mock_future, sample_batch, 10.0, mock_callback)
    
    def recover():
        watchdog.check_and_recover()
    
    for _ in range(5):
        threads.append(threading.Thread(target=add_task))
        threads.append(threading.Thread(target=recover))
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
        
    for item in watchdog._tracked:
        assert len(item) == 5