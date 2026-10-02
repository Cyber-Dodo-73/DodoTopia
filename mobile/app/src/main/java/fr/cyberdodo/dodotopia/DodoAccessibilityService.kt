package fr.cyberdodo.dodotopia

import android.accessibilityservice.AccessibilityService
import android.content.Intent
import android.content.res.Configuration
import android.graphics.Bitmap
import android.os.Build
import android.os.SystemClock
import android.view.Display
import android.view.KeyEvent
import android.view.accessibility.AccessibilityEvent
import androidx.lifecycle.MutableLiveData

/**
 * Le cœur de l'appli côté système : envoie les gestes, porte la bulle (fenêtre d'accessibilité,
 * donc sans SYSTEM_ALERT_WINDOW), intercepte volume bas et sait faire une capture de secours.
 * Il n'observe aucun contenu d'écran : onAccessibilityEvent reste vide.
 */
class DodoAccessibilityService : AccessibilityService() {

    lateinit var metronome: Metronome
        private set
    private var overlay: Overlay? = null

    /** Après avoir avalé l'appui de volume bas, on avale aussi son relâchement, sinon le volume bouge. */
    private var avalerRelachement = false

    override fun onServiceConnected() {
        SpikeLog.init(this)
        metronome = Metronome(this)
        overlay = Overlay(this).also { it.montrerBulle() }
        actif.value = true
        val e = tailleEcran(this)
        SpikeLog.log(
            "Service d'accessibilité connecté · ${Build.MANUFACTURER} ${Build.MODEL} · " +
                "Android ${Build.VERSION.RELEASE} (API ${Build.VERSION.SDK_INT}) · écran ${e.x}×${e.y}"
        )
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) = Unit

    override fun onInterrupt() = Unit

    override fun onKeyEvent(event: KeyEvent): Boolean {
        if (event.keyCode != KeyEvent.KEYCODE_VOLUME_DOWN) return false
        if (event.action == KeyEvent.ACTION_DOWN && metronome.enCours) {
            SpikeLog.log("Volume bas : arrêt")
            overlay?.arreterMesure()
            avalerRelachement = true
            return true
        }
        if (event.action == KeyEvent.ACTION_UP && avalerRelachement) {
            avalerRelachement = false
            return true
        }
        // Hors mesure, la touche garde son rôle normal.
        return false
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        overlay?.surRotation()
    }

    override fun onUnbind(intent: Intent?): Boolean {
        fermer()
        return super.onUnbind(intent)
    }

    override fun onDestroy() {
        fermer()
        super.onDestroy()
    }

    private fun fermer() {
        val o = overlay ?: return
        overlay = null
        o.fermerTout()
        metronome.fermer()
        actif.value = false
        SpikeLog.log("Service d'accessibilité arrêté")
    }

    /**
     * Capture de secours par le service (Android 11+, 3 par seconde au mieux).
     * Mesure le temps de la capture seule, puis celui de la copie en mémoire lisible,
     * parce que la cuisine aurait besoin des deux.
     */
    fun capturer(surFin: (String) -> Unit) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) {
            val texte = "Capture par le service : indisponible avant Android 11 (ici API ${Build.VERSION.SDK_INT})."
            SpikeLog.log(texte)
            surFin(texte)
            return
        }
        val debut = SystemClock.elapsedRealtime()
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(resultat: ScreenshotResult) {
                val capture = SystemClock.elapsedRealtime() - debut
                val tampon = resultat.hardwareBuffer
                val image = Bitmap.wrapHardwareBuffer(tampon, resultat.colorSpace)
                    ?.copy(Bitmap.Config.ARGB_8888, false)
                tampon.close()
                val texte = if (image == null) {
                    "Capture par le service : reçue en $capture ms mais illisible."
                } else {
                    val copie = SystemClock.elapsedRealtime() - debut - capture
                    val centre = luminosite(image.getPixel(image.width / 2, image.height / 2))
                    var somme = 0
                    for (i in 0 until GRILLE) for (j in 0 until GRILLE) {
                        somme += luminosite(
                            image.getPixel(image.width * (2 * i + 1) / (2 * GRILLE), image.height * (2 * j + 1) / (2 * GRILLE))
                        )
                    }
                    val moyenne = somme / (GRILLE * GRILLE)
                    val l = image.width
                    val h = image.height
                    image.recycle()
                    "Capture par le service : $capture ms (+ $copie ms de copie) · $l×$h · " +
                        "luminosité centre $centre, moyenne $moyenne" +
                        if (centre == 0 && moyenne == 0) " · NOIR : fenêtre protégée ?" else ""
                }
                SpikeLog.log(texte)
                surFin(texte)
            }

            override fun onFailure(code: Int) {
                val raison = when (code) {
                    ERROR_TAKE_SCREENSHOT_INTERNAL_ERROR -> "erreur interne"
                    ERROR_TAKE_SCREENSHOT_NO_ACCESSIBILITY_ACCESS -> "accès refusé au service"
                    ERROR_TAKE_SCREENSHOT_INTERVAL_TIME_SHORT -> "captures trop rapprochées"
                    ERROR_TAKE_SCREENSHOT_INVALID_DISPLAY -> "écran invalide"
                    else -> "code $code"
                }
                val texte = "Capture par le service : échec ($raison) après ${SystemClock.elapsedRealtime() - debut} ms."
                SpikeLog.log(texte)
                surFin(texte)
            }
        })
    }

    companion object {
        /** Vrai tant que le service est connecté : l'activité s'y abonne pour son état. */
        val actif = MutableLiveData(false)

        private const val GRILLE = 5
    }
}
