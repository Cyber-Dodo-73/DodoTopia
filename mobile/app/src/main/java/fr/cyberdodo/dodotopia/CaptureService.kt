package fr.cyberdodo.dodotopia

import android.Manifest
import android.annotation.SuppressLint
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioPlaybackCaptureConfiguration
import android.media.AudioRecord
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.SystemClock
import androidx.annotation.RequiresApi
import java.util.Locale
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread
import kotlin.math.abs
import kotlin.math.sqrt

/**
 * Test de capture de l'étape 1 : 6 s d'attente (le temps de revenir sur le jeu), puis 3 s
 * d'images et de son du jeu en même temps. Répond à deux questions : Heartopia se laisse-t-il
 * filmer (FLAG_SECURE donnerait du noir) et laisse-t-il capturer son audio ?
 *
 * Ordre imposé par Android 14+ : startForeground (type mediaProjection) AVANT getMediaProjection,
 * registerCallback AVANT createVirtualDisplay, et un jeton de consentement ne sert qu'une fois.
 */
class CaptureService : Service() {

    private var enCours = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        SpikeLog.init(this)
        val donnees: Intent? = intent?.let {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) it.getParcelableExtra(EXTRA_DONNEES, Intent::class.java)
            else @Suppress("DEPRECATION") it.getParcelableExtra(EXTRA_DONNEES)
        }
        if (donnees == null || enCours) {
            if (!enCours) stopSelf()
            return START_NOT_STICKY
        }
        enCours = true

        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                startForeground(ID_NOTIFICATION, notification(), ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION)
            } else {
                startForeground(ID_NOTIFICATION, notification())
            }
            val gestionnaire = getSystemService(MediaProjectionManager::class.java)
            val projection = gestionnaire.getMediaProjection(Activity.RESULT_OK, donnees)
                ?: throw IllegalStateException("projection refusée par le système")
            thread(name = "DodoCapture") { derouler(projection) }
        } catch (e: RuntimeException) {
            terminer("Capture impossible : ${e.javaClass.simpleName} ${e.message.orEmpty()}")
        }
        return START_NOT_STICKY
    }

    private fun derouler(projection: MediaProjection) {
        val filImages = HandlerThread("DodoCaptureImages").apply { start() }
        val handlerImages = Handler(filImages.looper)
        var texte: String
        try {
            // Si l'utilisateur coupe le partage depuis la barre d'état, on le saura dans le journal.
            projection.registerCallback(object : MediaProjection.Callback() {
                override fun onStop() {
                    SpikeLog.log("Projection arrêtée")
                }
            }, handlerImages)

            for (s in ATTENTE_S downTo 1) {
                Resultats.capture.postValue("Retourne sur Heartopia, bouge la caméra et joue une note… $s")
                Thread.sleep(1000)
            }
            Resultats.capture.postValue("Mesure en cours ($DUREE_MS ms)…")

            val ecran = tailleEcran(this)
            val images = AtomicInteger()
            var centre = -1
            var moyenne = -1
            val lecteur = ImageReader.newInstance(ecran.x, ecran.y, PixelFormat.RGBA_8888, 3)
            lecteur.setOnImageAvailableListener({ source ->
                val image = try {
                    source.acquireLatestImage()
                } catch (e: IllegalStateException) {
                    null
                } ?: return@setOnImageAvailableListener
                images.incrementAndGet()
                // RGBA sur un seul plan ; la ligne peut être plus large que l'image (rowStride).
                val plan = image.planes[0]
                val octets = plan.buffer
                fun lum(x: Int, y: Int): Int {
                    val i = y * plan.rowStride + x * plan.pixelStride
                    return luminosite(octets.get(i).toInt() and 0xff, octets.get(i + 1).toInt() and 0xff, octets.get(i + 2).toInt() and 0xff)
                }
                centre = lum(image.width / 2, image.height / 2)
                var somme = 0
                for (i in 0 until GRILLE) for (j in 0 until GRILLE) {
                    somme += lum(image.width * (2 * i + 1) / (2 * GRILLE), image.height * (2 * j + 1) / (2 * GRILLE))
                }
                moyenne = somme / (GRILLE * GRILLE)
                image.close()
            }, handlerImages)

            val affichage = projection.createVirtualDisplay(
                "DodoTopiaTest", ecran.x, ecran.y, resources.displayMetrics.densityDpi,
                DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR, lecteur.surface, null, handlerImages
            )

            // Le son se mesure sur ce fil pendant que les images arrivent sur l'autre : même fenêtre de 3 s.
            val debut = SystemClock.elapsedRealtime()
            val son = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                mesurerSon(projection)
            } else {
                "Son : capture du son des applis indisponible avant Android 10."
            }
            val reste = DUREE_MS - (SystemClock.elapsedRealtime() - debut)
            if (reste > 0) Thread.sleep(reste)
            val duree = SystemClock.elapsedRealtime() - debut

            affichage.release()
            // Le dernier rappel d'image doit être fini avant de lire les compteurs et de fermer le lecteur.
            filImages.quitSafely()
            filImages.join(1000)
            lecteur.close()

            val n = images.get()
            val cadence = n * 1000.0 / duree
            texte = String.format(
                Locale.FRANCE,
                "Écran : %d images en %.1f s (%.1f images/s) · %d×%d · luminosité centre %d, moyenne %d%s\n%s",
                n, duree / 1000.0, cadence, ecran.x, ecran.y, centre, moyenne,
                when {
                    n == 0 -> " · AUCUNE IMAGE"
                    centre == 0 && moyenne == 0 -> " · NOIR : fenêtre protégée (FLAG_SECURE) ?"
                    else -> ""
                },
                son
            )
        } catch (e: Exception) {
            texte = "Capture interrompue : ${e.javaClass.simpleName} ${e.message.orEmpty()}"
        } finally {
            filImages.quitSafely()
            try {
                projection.stop()
            } catch (e: RuntimeException) {
                // Déjà arrêtée par l'utilisateur.
            }
        }
        terminer(texte)
    }

    /** Enregistre 3 s du son joué par les autres applis (pas le micro) et renvoie pic et RMS sur 16 bits. */
    @RequiresApi(Build.VERSION_CODES.Q)
    @SuppressLint("MissingPermission")
    private fun mesurerSon(projection: MediaProjection): String {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            return "Son : non mesuré, permission d'enregistrement refusée (Android l'exige pour capturer le son du jeu)."
        }
        val config = AudioPlaybackCaptureConfiguration.Builder(projection)
            .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
            .addMatchingUsage(AudioAttributes.USAGE_GAME)
            .addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
            .build()
        val format = AudioFormat.Builder()
            .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
            .setSampleRate(FREQUENCE)
            .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
            .build()
        val mini = AudioRecord.getMinBufferSize(FREQUENCE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val micro = AudioRecord.Builder()
            .setAudioFormat(format)
            .setBufferSizeInBytes(maxOf(mini * 2, FREQUENCE))
            .setAudioPlaybackCaptureConfig(config)
            .build()
        if (micro.state != AudioRecord.STATE_INITIALIZED) {
            micro.release()
            return "Son : AudioRecord n'a pas pu s'initialiser."
        }
        val tampon = ShortArray(FREQUENCE / 10)
        var pic = 0
        var carres = 0.0
        var total = 0L
        try {
            micro.startRecording()
            val fin = SystemClock.elapsedRealtime() + DUREE_MS
            while (SystemClock.elapsedRealtime() < fin) {
                val lus = micro.read(tampon, 0, tampon.size)
                if (lus <= 0) break
                for (k in 0 until lus) {
                    val v = tampon[k].toInt()
                    if (abs(v) > pic) pic = abs(v)
                    carres += v.toDouble() * v
                }
                total += lus
            }
            micro.stop()
        } finally {
            micro.release()
        }
        if (total == 0L) return "Son : aucun échantillon reçu."
        val rms = sqrt(carres / total)
        return String.format(
            Locale.FRANCE, "Son : pic %d · RMS %.1f (sur 32767) · %.1f s%s",
            pic, rms, total / FREQUENCE.toDouble(),
            when {
                pic == 0 -> " · SILENCE TOTAL : le jeu interdit la capture de son audio (ou rien ne jouait)"
                pic <= SEUIL_PIC -> " · trop faible pour une synchro par le son"
                else -> ""
            }
        )
    }

    private fun terminer(texte: String) {
        SpikeLog.log(texte)
        Resultats.capture.postValue(texte)
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    private fun notification(): Notification {
        val gestionnaire = getSystemService(NotificationManager::class.java)
        gestionnaire.createNotificationChannel(
            NotificationChannel(CANAL, "Test de capture", NotificationManager.IMPORTANCE_LOW)
        )
        return Notification.Builder(this, CANAL)
            .setSmallIcon(R.drawable.ic_stat_dodo)
            .setContentTitle("DodoTopia teste la capture")
            .setContentText("Écran et son du jeu, quelques secondes.")
            .setOngoing(true)
            .build()
    }

    companion object {
        private const val EXTRA_DONNEES = "donnees"
        private const val CANAL = "capture"
        private const val ID_NOTIFICATION = 1
        private const val ATTENTE_S = 6
        private const val DUREE_MS = 3000L
        private const val FREQUENCE = 48000
        private const val GRILLE = 5

        /** Seuil du brief : en dessous, pas de synchro par le son. */
        private const val SEUIL_PIC = 50

        /** [donnees] est l'intention rendue par l'écran de consentement, à usage unique. */
        fun intention(context: Context, donnees: Intent): Intent =
            Intent(context, CaptureService::class.java).putExtra(EXTRA_DONNEES, donnees)
    }
}
