# DSI-011 Research Prompt Cookbook

Each prompt compiles into a visible typed specification before any governed
execution. Follow-ups create immutable child experiments.

## Alpha Signals

1. Backtest Alpha BUY and STRONG BUY recommendations since 2016.
2. Backtest only Alpha STRONG BUY recommendations and hold for 20 sessions.
3. Take Alpha BUY signals at the next valid session open.
4. Repeat the Alpha signal strategy with a maximum of five positions.
5. Run the same Alpha strategy only during bullish regimes.

## Pure Technical

6. Backtest RSI above 50 and price above the 200-DMA.
7. Buy when RSI crosses above 30 and volume is above its 20-session average.
8. Require price above the 50-DMA and the 50-DMA above the 200-DMA.
9. Enter when volume is at least twice its 20-session average.
10. Backtest ADX above 25 with price above the 200-DMA.

## Hybrid

11. Take Alpha BUY signals only when RSI is above 50.
12. Add price above the 200-DMA to Alpha BUY and STRONG BUY signals.
13. Require volume to be at least 1.5 times its 20-session average.
14. Add ADX above 25 and keep every other setting unchanged.
15. Remove all technical indicators but retain the Alpha signal source.

## Indicator Edits

16. Add RSI below 35 as an entry condition.
17. Change RSI from below 35 to below 40.
18. Use RSI over seven sessions instead of 14.
19. Remove RSI.
20. Remove only the volume filter.
21. Remove all volume conditions.
22. Require the stock to close above its 200-DMA.
23. Replace the 20-EMA with the 50-EMA.

## Candle Analysis

24. Add bullish engulfing as an entry confirmation.
25. Replace bullish engulfing with an inside-bar breakout.
26. Add a hammer as an entry confirmation.
27. Only enter when the candle closes in the top 20% of its range.
28. Remove bullish engulfing and keep the indicator filters.
29. Remove all candle analysis.

## Entries

30. Enter at the next session open.
31. Enter at the next session close.
32. Wait two sessions before entering.
33. Enter only if price breaks above the signal candle high.
34. Buy on a 3% retracement from the signal close.
35. Cancel the entry if it does not trigger within five sessions.

## Stops

36. Add an 8% stop.
37. Replace the 8% stop with a 2 ATR stop.
38. Place the stop below the signal candle low.
39. Place the stop below the latest swing low.
40. Use STOP-STRUCTURAL-10D.
41. Remove the stop.
42. Add a 10% trailing stop after the trade gains 15%.

## Targets and Exits

43. Add a 20% target.
44. Replace the target with 3R.
45. Use a target 4 ATR above entry.
46. Take half the position at 2R and trail the balance with a 10% stop.
47. Remove the fixed target but retain the time exit.
48. Exit at the earliest of 3R or 40 sessions.
49. Hold for a maximum of 20 sessions.

## Sweeps and Comparisons

50. Test RSI thresholds of 30, 35, 40 and 45.
51. Test holding periods of 5, 10, 20 and 40 sessions.
52. Test portfolio sizes of 5, 10 and 20 positions.
53. Compare experiments ARL-000012 and ARL-000013.
54. Show the trades responsible for most of the performance difference.
55. Repeat using target-first handling for ambiguous sessions.

## Inspection and Reset

56. Show me the complete strategy.
57. What indicators are active?
58. What is the current stop?
59. Which rules changed from experiment 12?
60. Reset the indicators to experiment 12.

Ambiguous prompts such as "buy good stocks after a correction" or "use a
reasonable stop" deliberately fail. State the measurable condition and exact
rule instead.
