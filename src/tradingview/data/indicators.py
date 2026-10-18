from __future__ import annotations

import copy
from typing import Any, Callable

from .._types import AttrDict
from ..chart.chart_session import ChartSession
from ..chart.study import Study
from ..errors import TradingViewError, to_trading_view_error
from ..http.indicators import get_indicator
from ..indicators import BuiltInIndicator, Indicator, PineIndicator
from .history import (
    HistoryPlan,
    load_history,
    no_data_error,
    open_market,
    plan_history,
    select_candles,
)
from .operation import (
    Watcher,
    _get_handler,
    run_operation,
    start_watcher,
    throw_if_aborted,
)

IndicatorQuery = dict[str, Any]
IndicatorData = AttrDict
IndicatorHandlers = dict[str, Any]


async def resolve_indicator(query: IndicatorQuery) -> Indicator:
    """Resolves an indicator ID or instance and applies inputs."""
    indicator = query.get("indicator")
    inputs = query.get("inputs") or {}

    if isinstance(indicator, PineIndicator):
        resolved: Indicator = indicator.clone()
    elif isinstance(indicator, BuiltInIndicator):
        resolved = BuiltInIndicator(indicator.type, indicator.options)
    elif isinstance(indicator, str) and indicator.strip():
        if "@" in indicator:
            resolved = BuiltInIndicator(indicator)
        else:
            client_opts = query.get("clientOptions") or query.get("client_options") or {}
            resolved = await get_indicator(
                indicator,
                {
                    "version": query.get("version"),
                    "credentials": query.get("credentials"),
                    "signal": query.get("signal"),
                    "fetch": client_opts.get("fetch"),
                },
            )
    else:
        raise TradingViewError(
            "INVALID_ARGUMENT",
            "indicator must be a script ID, a built-in type or an indicator instance",
        )

    for key, value in inputs.items():
        if isinstance(resolved, PineIndicator):
            resolved.set_input(key, value)
        else:
            resolved.set_option(key, value)
    return resolved


resolveIndicator = resolve_indicator


def _snapshot(chart: ChartSession, study: Study, plan: HistoryPlan) -> IndicatorData:
    return AttrDict(
        {
            "indicator": study.indicator,
            "candles": select_candles(chart.candles, plan),
            "values": study.values,
            "graphics": study.graphics,
            "strategyReport": copy.deepcopy(study.strategy_report),
        }
    )


def _track_readiness(
    chart: ChartSession,
    study: Study,
    plan: HistoryPlan,
    deep: bool,
    on_ready: Callable[[], None],
    on_empty: Callable[[TradingViewError], None],
) -> None:
    history_done = False
    study_loading = True
    fired = False

    def check() -> None:
        nonlocal fired
        if fired or not history_done or study_loading:
            return
        fired = True
        on_ready()

    def _on_loading() -> None:
        nonlocal study_loading
        study_loading = True

    def _on_study_ready() -> None:
        nonlocal study_loading
        study_loading = False
        check()

    def _on_history_done(info: Any) -> None:
        nonlocal fired, history_done
        if len(chart.candles) == 0:
            fired = True
            on_empty(no_data_error(plan["symbol"], info))
            return
        history_done = True
        check()

    study.on("loading", _on_loading)
    study.on("ready", _on_study_ready)
    load_history(chart, plan, deep, _on_history_done)


def _prepare(query: IndicatorQuery) -> HistoryPlan:
    return plan_history({**query, "from": None})


class IndicatorWatcher(Watcher):
    def __init__(self, base: Watcher, get_latest: Callable[[], IndicatorData | None]) -> None:
        super().__init__(base.stop, base.closed, lambda: base.is_active)
        self._get_latest = get_latest

    @property
    def latest(self) -> IndicatorData | None:
        return self._get_latest()


async def get_indicator_data(
    query: IndicatorQuery | None = None,
    **kwargs: Any,
) -> IndicatorData:
    """Runs an indicator or strategy once and returns its values, drawings and strategy report."""
    options = {**(query or {}), **kwargs}
    plan = _prepare(options)
    throw_if_aborted(options.get("signal"))
    try:
        indicator = await resolve_indicator(options)
    except BaseException as err:
        raise to_trading_view_error(err, "NOT_FOUND") from err

    def _start(ctx: Any) -> Callable[[], None]:
        chart = ctx.client.create_chart()
        chart.on("error", ctx.reject)
        open_market(chart, plan)
        study = chart.create_study(indicator)
        study.on("error", ctx.reject)
        _track_readiness(
            chart,
            study,
            plan,
            True,
            lambda: ctx.resolve(_snapshot(chart, study, plan)),
            ctx.reject,
        )
        return chart.delete

    return await run_operation(options, f"getIndicatorData({plan['symbol']})", _start)


getIndicatorData = get_indicator_data


async def watch_indicator(
    query: IndicatorQuery,
    handlers: Any = None,
    **kwargs: Any,
) -> IndicatorWatcher:
    """Streams an indicator in real time. Call stop() when finished."""
    options = {**(query or {}), **kwargs}
    on_data = _get_handler(handlers, "onData", "on_data")
    if not callable(on_data):
        raise TradingViewError("INVALID_ARGUMENT", "onData must be a function")
    plan = _prepare({**options, "to": None})
    throw_if_aborted(options.get("signal"))
    try:
        indicator = await resolve_indicator(options)
    except BaseException as err:
        raise to_trading_view_error(err, "NOT_FOUND") from err

    latest: IndicatorData | None = None

    def _start(ctx: Any) -> Callable[[], None]:
        nonlocal latest
        chart = ctx.client.create_chart()
        started = False

        chart.on("error", lambda err: ctx.fail(err))
        open_market(chart, plan)
        study = chart.create_study(indicator)
        study.on("error", lambda err: ctx.fail(err))

        def publish() -> None:
            nonlocal latest
            latest = _snapshot(chart, study, plan)
            try:
                on_data(latest)
            except BaseException as err:
                ctx.warn(TradingViewError("CALLBACK_ERROR", "onData callback threw", cause=err))

        study.on("update", lambda *_: publish() if (started and ctx.is_active()) else None)

        def _on_ready() -> None:
            nonlocal started
            started = True
            publish()
            ctx.ready()

        _track_readiness(chart, study, plan, False, _on_ready, lambda err: ctx.fail(err))
        return chart.delete

    return await start_watcher(
        options,
        f"watchIndicator({plan['symbol']})",
        handlers,
        _start,
        lambda base: IndicatorWatcher(base, lambda: latest),
    )


watchIndicator = watch_indicator
