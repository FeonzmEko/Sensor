package com.example.sensorlog

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.util.AttributeSet
import android.util.TypedValue
import android.view.View
import java.util.ArrayDeque

/**
 * 实时滚动波形：最近 windowMs 毫秒内的最多 3 条曲线（X/Y/Z）。
 * 纵轴固定量程 [yMin, yMax]，横轴按真实时间戳滚动，可直观看到采样与抖动。
 */
class WaveformView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null
) : View(context, attrs) {

    /** 显示窗口长度（毫秒） */
    var windowMs = 8000L
    /** 纵轴范围 */
    var yMin = -25f
    var yMax = 25f
    /** 每条曲线颜色（X/Y/Z） */
    var seriesColors = intArrayOf(
        0xFFFF5252.toInt(), // 红 X
        0xFF69F0AE.toInt(), // 绿 Y
        0xFF448AFF.toInt()  // 蓝 Z
    )
    /** 图例文字 */
    var seriesNames = arrayOf("X", "Y", "Z")

    private class Sample(val tMs: Long, val x: Float, val y: Float, val z: Float)

    private val data = ArrayDeque<Sample>()

    private val bgPaint = Paint().apply {
        color = 0xFF101418.toInt()
        style = Paint.Style.FILL
    }
    private val gridPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFF2A323B.toInt()
        strokeWidth = dp(1f)
    }
    private val zeroPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFF4A5560.toInt()
        strokeWidth = dp(1.5f)
    }
    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeJoin = Paint.Join.ROUND
        strokeCap = Paint.Cap.ROUND
        strokeWidth = dp(2.5f)
    }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFFB0BEC5.toInt()
        textSize = sp(10f)
    }
    private val path = Path()

    private fun dp(v: Float) = v * resources.displayMetrics.density

    /** sp → px：按系统字体缩放换算。 */
    private fun sp(v: Float) = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_SP, v, resources.displayMetrics
    )

    /** 追加一个采样点：tMs 为时间轴（ms），values 为各通道数值 */
    fun addSample(tMs: Long, values: FloatArray) {
        data.addLast(Sample(tMs, values.getOrElse(0) { 0f }, values.getOrElse(1) { 0f }, values.getOrElse(2) { 0f }))
        val cutoff = tMs - windowMs
        while (data.isNotEmpty() && data.first().tMs < cutoff) data.removeFirst()
        invalidate()
    }

    fun clear() {
        data.clear()
        invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val w = width.toFloat()
        val h = height.toFloat()
        val padL = dp(34f)          // 左侧留纵轴刻度
        val padR = dp(6f)
        val padT = dp(20f)          // 顶部留图例
        val padB = dp(6f)
        val pw = w - padL - padR
        val ph = h - padT - padB

        canvas.drawRect(0f, 0f, w, h, bgPaint)

        if (pw <= 0 || ph <= 0) return

        fun mapY(v: Float): Float = padT + ph * (yMax - v) / (yMax - yMin)
        val newestT = data.lastOrNull()?.tMs ?: 0L
        val oldestT = newestT - windowMs
        fun mapX(tMs: Long): Float =
            padL + pw * (tMs - oldestT).toFloat() / windowMs.toFloat()

        // 纵向网格：每 5 m/s² 一条 + 刻度文字
        val step = 5f
        var gy = (yMin / step).toInt() * step
        while (gy <= yMax) {
            val y = mapY(gy.toFloat())
            canvas.drawLine(padL, y, w - padR, y, gridPaint)
            canvas.drawText(if (gy == 0f) "0" else gy.toInt().toString(), dp(4f), y + dp(3.5f), textPaint)
            gy += step.toInt()
        }
        // 横向网格：每 1 秒一条
        var markerMs = (oldestT / 1000L + 1L) * 1000L
        while (markerMs <= newestT) {
            val x = mapX(markerMs)
            canvas.drawLine(x, padT, x, padT + ph, gridPaint)
            markerMs += 1000L
        }
        // 零线加亮
        canvas.drawLine(padL, mapY(0f), w - padR, mapY(0f), zeroPaint)

        // 曲线：使用 save/restore 限定绘图区；单点也绘制实心标记。
        if (data.isNotEmpty()) {
            val saveCount = canvas.save()
            canvas.clipRect(padL, padT, w - padR, padT + ph)
            for (s in 0 until 3) {
                linePaint.color = seriesColors[s]
                path.reset()
                var first = true
                for (d in data) {
                    val x = mapX(d.tMs)
                    val y = mapY(when (s) {
                        0 -> d.x; 1 -> d.y; else -> d.z
                    })
                    if (first) { path.moveTo(x, y); first = false } else path.lineTo(x, y)
                }
                if (data.size >= 2) {
                    canvas.drawPath(path, linePaint)
                }

                val latest = data.last()
                val latestY = mapY(when (s) {
                    0 -> latest.x; 1 -> latest.y; else -> latest.z
                })
                linePaint.style = Paint.Style.FILL
                canvas.drawCircle(mapX(latest.tMs), latestY, dp(2.5f), linePaint)
                linePaint.style = Paint.Style.STROKE
            }
            canvas.restoreToCount(saveCount)
        }

        // 图例
        var lx = padL
        for (s in 0 until 3) {
            textPaint.color = seriesColors[s]
            canvas.drawText(seriesNames[s], lx, dp(14f), textPaint)
            lx += textPaint.measureText(seriesNames[s]) + dp(10f)
        }
        textPaint.color = 0xFF78909C.toInt()
        canvas.drawText("(m/s²)", lx, dp(14f), textPaint)
        textPaint.color = 0xFFB0BEC5.toInt()
    }
}
