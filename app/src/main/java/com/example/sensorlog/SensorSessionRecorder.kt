package com.example.sensorlog

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.os.Build
import android.os.SystemClock
import org.json.JSONObject
import java.io.BufferedWriter
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.OutputStreamWriter
import java.nio.charset.StandardCharsets
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

internal data class SensorSampleStats(
    val sampleCount: Long,
    val firstTimestampNs: Long?,
    val lastTimestampNs: Long?,
) {
    val durationSeconds: Double
        get() {
            val first = firstTimestampNs ?: return 0.0
            val last = lastTimestampNs ?: return 0.0
            return (last - first) / 1_000_000_000.0
        }

    val measuredHz: Double
        get() = if (sampleCount > 1 && durationSeconds > 0.0) {
            (sampleCount - 1) / durationSeconds
        } else {
            0.0
        }
}

internal data class RecorderSnapshot(
    val active: Boolean,
    val accelerometerCount: Long,
    val gyroscopeCount: Long,
    val error: String?,
)

internal data class RecordingSummary(
    val sessionId: String,
    val directory: File,
    val accelerometer: SensorSampleStats,
    val gyroscope: SensorSampleStats,
    val error: String?,
)

/**
 * 将 SensorEvent 原样写入两个 CSV：
 * - accelerometer.csv: timestamp_ns,x_m_s2,y_m_s2,z_m_s2
 * - gyroscope.csv: timestamp_ns,x_rad_s,y_rad_s,z_rad_s
 *
 * 不执行滤波、插值、坐标旋转、单位换算或降采样。metadata.json 同时记录
 * 设备、传感器参数、采集时间和完成状态，便于后续追溯。
 */
internal class SensorSessionRecorder(context: Context) {

    private val appContext = context.applicationContext
    private val lock = Any()

    private var active = false
    private var sessionId: String? = null
    private var sessionDirectory: File? = null
    private var accelerometerWriter: BufferedWriter? = null
    private var gyroscopeWriter: BufferedWriter? = null

    private var accelerometer: Sensor? = null
    private var gyroscope: Sensor? = null

    private var startedAtEpochMs = 0L
    private var startedAtElapsedNs = 0L
    private var endedAtEpochMs: Long? = null
    private var endedAtElapsedNs: Long? = null

    private var accelerometerCount = 0L
    private var gyroscopeCount = 0L
    private var accelerometerFirstTimestampNs: Long? = null
    private var accelerometerLastTimestampNs: Long? = null
    private var gyroscopeFirstTimestampNs: Long? = null
    private var gyroscopeLastTimestampNs: Long? = null

    private var rowsSinceFlush = 0
    private var recordingError: String? = null

    fun isRecording(): Boolean = synchronized(lock) { active }

    fun snapshot(): RecorderSnapshot = synchronized(lock) {
        RecorderSnapshot(
            active = active,
            accelerometerCount = accelerometerCount,
            gyroscopeCount = gyroscopeCount,
            error = recordingError,
        )
    }

    @Throws(IOException::class)
    fun start(accelerometer: Sensor, gyroscope: Sensor): File = synchronized(lock) {
        check(!active) { "已有采集会话正在进行" }

        resetState()
        this.accelerometer = accelerometer
        this.gyroscope = gyroscope

        val storageRoot = appContext.getExternalFilesDir(null) ?: appContext.filesDir
        val sessionsRoot = File(storageRoot, "sensor-sessions")
        if (!sessionsRoot.exists() && !sessionsRoot.mkdirs()) {
            throw IOException("无法创建采集目录：${sessionsRoot.absolutePath}")
        }

        val baseSessionId = SimpleDateFormat("yyyyMMdd_HHmmss_SSS", Locale.US).format(Date())
        var candidate = File(sessionsRoot, baseSessionId)
        var suffix = 2
        while (candidate.exists()) {
            candidate = File(sessionsRoot, "${baseSessionId}_$suffix")
            suffix++
        }
        if (!candidate.mkdirs()) {
            throw IOException("无法创建采集会话目录：${candidate.absolutePath}")
        }

        sessionId = candidate.name
        sessionDirectory = candidate
        startedAtEpochMs = System.currentTimeMillis()
        startedAtElapsedNs = SystemClock.elapsedRealtimeNanos()

        try {
            accelerometerWriter = openWriter(
                file = File(candidate, "accelerometer.csv"),
                header = "timestamp_ns,x_m_s2,y_m_s2,z_m_s2",
            )
            gyroscopeWriter = openWriter(
                file = File(candidate, "gyroscope.csv"),
                header = "timestamp_ns,x_rad_s,y_rad_s,z_rad_s",
            )
            active = true
            writeMetadataLocked(status = "recording", stopReason = null)
            candidate
        } catch (t: Throwable) {
            active = false
            recordingError = t.message ?: t.javaClass.simpleName
            closeWritersLocked()
            throw t
        }
    }

    fun write(event: SensorEvent) {
        val sensorType = event.sensor.type
        if (sensorType != Sensor.TYPE_ACCELEROMETER && sensorType != Sensor.TYPE_GYROSCOPE) {
            return
        }

        synchronized(lock) {
            if (!active) return

            try {
                when (sensorType) {
                    Sensor.TYPE_ACCELEROMETER -> {
                        writeRow(accelerometerWriter ?: return, event)
                        accelerometerCount++
                        if (accelerometerFirstTimestampNs == null) {
                            accelerometerFirstTimestampNs = event.timestamp
                        }
                        accelerometerLastTimestampNs = event.timestamp
                    }

                    Sensor.TYPE_GYROSCOPE -> {
                        writeRow(gyroscopeWriter ?: return, event)
                        gyroscopeCount++
                        if (gyroscopeFirstTimestampNs == null) {
                            gyroscopeFirstTimestampNs = event.timestamp
                        }
                        gyroscopeLastTimestampNs = event.timestamp
                    }
                }

                rowsSinceFlush++
                if (rowsSinceFlush >= FLUSH_EVERY_ROWS) {
                    flushWritersLocked()
                }
            } catch (t: Throwable) {
                recordingError = t.message ?: t.javaClass.simpleName
            }
        }
    }

    fun stop(stopReason: String): RecordingSummary? = synchronized(lock) {
        if (!active) return null

        active = false
        endedAtEpochMs = System.currentTimeMillis()
        endedAtElapsedNs = SystemClock.elapsedRealtimeNanos()

        try {
            flushWritersLocked()
        } catch (t: Throwable) {
            recordingError = t.message ?: t.javaClass.simpleName
        } finally {
            closeWritersLocked()
        }

        val stats = buildSummaryLocked()
        try {
            writeMetadataLocked(status = "completed", stopReason = stopReason)
        } catch (t: Throwable) {
            recordingError = t.message ?: t.javaClass.simpleName
        }
        stats.copy(error = recordingError)
    }

    private fun resetState() {
        active = false
        sessionId = null
        sessionDirectory = null
        accelerometerWriter = null
        gyroscopeWriter = null
        accelerometer = null
        gyroscope = null
        startedAtEpochMs = 0L
        startedAtElapsedNs = 0L
        endedAtEpochMs = null
        endedAtElapsedNs = null
        accelerometerCount = 0L
        gyroscopeCount = 0L
        accelerometerFirstTimestampNs = null
        accelerometerLastTimestampNs = null
        gyroscopeFirstTimestampNs = null
        gyroscopeLastTimestampNs = null
        rowsSinceFlush = 0
        recordingError = null
    }

    private fun openWriter(file: File, header: String): BufferedWriter {
        val writer = BufferedWriter(
            OutputStreamWriter(FileOutputStream(file), StandardCharsets.UTF_8),
        )
        writer.write(header)
        writer.newLine()
        return writer
    }

    private fun writeRow(writer: BufferedWriter, event: SensorEvent) {
        writer.write(event.timestamp.toString())
        writer.write(",")
        writer.write(event.values[0].toString())
        writer.write(",")
        writer.write(event.values[1].toString())
        writer.write(",")
        writer.write(event.values[2].toString())
        writer.newLine()
    }

    private fun flushWritersLocked() {
        accelerometerWriter?.flush()
        gyroscopeWriter?.flush()
        rowsSinceFlush = 0
    }

    private fun closeWritersLocked() {
        accelerometerWriter?.let { writer ->
            try {
                writer.flush()
            } catch (_: Throwable) {
            }
            try {
                writer.close()
            } catch (_: Throwable) {
            }
        }
        gyroscopeWriter?.let { writer ->
            try {
                writer.flush()
            } catch (_: Throwable) {
            }
            try {
                writer.close()
            } catch (_: Throwable) {
            }
        }
        accelerometerWriter = null
        gyroscopeWriter = null
    }

    private fun buildSummaryLocked(): RecordingSummary {
        val accelerometerStats = SensorSampleStats(
            sampleCount = accelerometerCount,
            firstTimestampNs = accelerometerFirstTimestampNs,
            lastTimestampNs = accelerometerLastTimestampNs,
        )
        val gyroscopeStats = SensorSampleStats(
            sampleCount = gyroscopeCount,
            firstTimestampNs = gyroscopeFirstTimestampNs,
            lastTimestampNs = gyroscopeLastTimestampNs,
        )
        return RecordingSummary(
            sessionId = sessionId.orEmpty(),
            directory = sessionDirectory ?: appContext.filesDir,
            accelerometer = accelerometerStats,
            gyroscope = gyroscopeStats,
            error = recordingError,
        )
    }

    private fun writeMetadataLocked(status: String, stopReason: String?) {
        val directory = sessionDirectory ?: return
        val accelerometerStats = SensorSampleStats(
            sampleCount = accelerometerCount,
            firstTimestampNs = accelerometerFirstTimestampNs,
            lastTimestampNs = accelerometerLastTimestampNs,
        )
        val gyroscopeStats = SensorSampleStats(
            sampleCount = gyroscopeCount,
            firstTimestampNs = gyroscopeFirstTimestampNs,
            lastTimestampNs = gyroscopeLastTimestampNs,
        )

        val root = JSONObject()
            .put("schema_version", 1)
            .put("session_id", sessionId)
            .put("status", status)
            .put("stop_reason", stopReason ?: JSONObject.NULL)
            .put("started_at", formatEpoch(startedAtEpochMs))
            .put("ended_at", formatEpoch(endedAtEpochMs))
            .put("started_elapsed_realtime_ns", startedAtElapsedNs)
            .put("ended_elapsed_realtime_ns", endedAtElapsedNs ?: JSONObject.NULL)
            .put("sample_clock", "SensorEvent.timestamp, nanoseconds, same boot-time clock for both sensors")
            .put("coordinate_system", "Android device body frame X/Y/Z")

        val device = JSONObject()
            .put("manufacturer", Build.MANUFACTURER)
            .put("model", Build.MODEL)
            .put("device", Build.DEVICE)
            .put("android_release", Build.VERSION.RELEASE)
            .put("android_sdk", Build.VERSION.SDK_INT)
        root.put("device", device)

        val sensors = JSONObject()
            .put("accelerometer", sensorJson(accelerometer))
            .put("gyroscope", sensorJson(gyroscope))
        root.put("sensors", sensors)

        val samples = JSONObject()
            .put("accelerometer", sampleJson("m/s^2", accelerometerStats))
            .put("gyroscope", sampleJson("rad/s", gyroscopeStats))
        root.put("samples", samples)
        root.put("error", recordingError ?: JSONObject.NULL)

        File(directory, "metadata.json").writeText(root.toString(2), Charsets.UTF_8)
    }

    private fun sensorJson(sensor: Sensor?): JSONObject {
        if (sensor == null) return JSONObject()
        return JSONObject()
            .put("name", sensor.name)
            .put("vendor", sensor.vendor)
            .put("version", sensor.version)
            .put("type", sensor.type)
            .put("max_range", sensor.maximumRange)
            .put("resolution", sensor.resolution)
            .put("min_delay_us", sensor.minDelay)
            .put("reporting_mode", sensor.reportingMode)
    }

    private fun sampleJson(unit: String, stats: SensorSampleStats): JSONObject {
        return JSONObject()
            .put("unit", unit)
            .put("sample_count", stats.sampleCount)
            .put("first_timestamp_ns", stats.firstTimestampNs ?: JSONObject.NULL)
            .put("last_timestamp_ns", stats.lastTimestampNs ?: JSONObject.NULL)
            .put("duration_seconds", stats.durationSeconds)
            .put("measured_hz", stats.measuredHz)
    }

    private fun formatEpoch(epochMs: Long?): Any {
        if (epochMs == null || epochMs <= 0L) return JSONObject.NULL
        return SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS Z", Locale.US).format(Date(epochMs))
    }

    private companion object {
        const val FLUSH_EVERY_ROWS = 200
    }
}