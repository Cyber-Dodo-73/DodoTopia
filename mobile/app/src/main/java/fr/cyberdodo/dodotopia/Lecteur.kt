package fr.cyberdodo.dodotopia

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.graphics.Path
import android.graphics.PointF
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.Process
import android.os.SystemClock
import kotlin.math.max

/**
 * Joue un morceau arrangé en envoyant des appuis sur les touches calibrées.
 *
 * dispatchGesture ne tient qu'un geste à la fois : en envoyer un pendant qu'un autre est en cours
 * annule le premier. Les appuis qui se chevauchent (accords, notes rapprochées) partent donc dans
 * un même geste, chacun avec son décalage ; un nouveau geste n'est envoyé qu'une fois le précédent fini.
 * Le découpage lui-même est dans [Gestes] (sans Android, donc testable) ; ici, l'horloge et l'envoi.
 * Même fil dédié que le métronome de test, pour que les fenêtres ne retardent pas les envois.
 */
class Lecteur(private val service: AccessibilityService) {

    private class Seance(val vitesse: Float, val depuisMs: Long) {
        /** Instant (uptimeMillis) où la position [depuisMs] du morceau est jouée. */
        @Volatile
        var t0 = 0L
        var envoyes = 0
        var refuses = 0
        var annules = 0
        var tenue = false
    }

    private val fil = HandlerThread("DodoLecteur", Process.THREAD_PRIORITY_URGENT_AUDIO).apply { start() }
    private val handler = Handler(fil.looper)
    private val principal = Handler(Looper.getMainLooper())

    @Volatile
    private var seance: Seance? = null

    val enCours: Boolean get() = seance != null

    /** Position dans le morceau, en millisecondes du morceau (indépendante de la vitesse). */
    fun positionMs(): Long {
        val s = seance ?: return 0
        if (s.t0 == 0L) return s.depuisMs
        return s.depuisMs + (max(0, SystemClock.uptimeMillis() - s.t0) * s.vitesse).toLong()
    }

    /**
     * [positions] : le centre de chaque touche à l'écran, dans l'ordre des notes du clavier.
     * [surFin] est appelé sur le fil principal quand le morceau est allé au bout (pas après [arreter]).
     */
    fun jouer(
        frappes: List<Frappe>, positions: List<PointF>, vitesse: Float, depuisMs: Long,
        appuiMs: Long, delaiMs: Long, surFin: () -> Unit,
    ) {
        if (enCours) return
        val s = Seance(vitesse, depuisMs)
        seance = s
        handler.post {
            val tenue = notesTenues(service)
            val traits = Gestes.traits(frappes, positions.size, vitesse, depuisMs, appuiMs, tenue)
            val t0 = SystemClock.uptimeMillis() + delaiMs
            s.t0 = t0
            s.tenue = tenue
            var fin = t0
            for (geste in Gestes.decouper(traits, tenue, appuiMs, MAX_TRAITS)) {
                handler.postAtTime({ envoyer(s, geste, positions) }, s, t0 + geste[0].debut)
                fin = max(fin, t0 + geste.maxOf { it.debut + it.duree })
            }
            handler.postAtTime({
                if (seance === s) {
                    seance = null
                    journal(s, "terminée")
                    principal.post(surFin)
                }
            }, s, fin + ATTENTE_FIN_MS)
        }
    }

    /** Arrête la lecture et rend la position atteinte. Appelable de n'importe quel fil. */
    fun arreter(): Long {
        val s = seance ?: return 0
        val position = positionMs()
        seance = null
        handler.removeCallbacksAndMessages(s)
        handler.post { journal(s, "arrêtée à $position ms") }
        return position
    }

    fun fermer() {
        seance = null
        fil.quitSafely()
    }

    private fun envoyer(s: Seance, traits: List<Trait>, positions: List<PointF>) {
        if (seance !== s) return
        val origine = traits[0].debut
        val geste = GestureDescription.Builder()
        for (t in traits) {
            val p = positions[t.touche]
            val x = p.x.coerceAtLeast(0f)
            val y = p.y.coerceAtLeast(0f)
            val chemin = Path().apply { moveTo(x, y); lineTo(x, y) }
            geste.addStroke(GestureDescription.StrokeDescription(chemin, t.debut - origine, max(Gestes.APPUI_MIN_MS, t.duree)))
        }
        val retour = object : AccessibilityService.GestureResultCallback() {
            override fun onCancelled(g: GestureDescription?) {
                s.annules++
            }
        }
        val accepte = try {
            service.dispatchGesture(geste.build(), retour, handler)
        } catch (e: RuntimeException) {
            false
        }
        s.envoyes++
        if (!accepte) s.refuses++
    }

    private fun journal(s: Seance, fin: String) {
        SpikeLog.log("Lecture $fin · ${s.envoyes} gestes · ${s.annules} annulés · ${s.refuses} refusés · vitesse ${s.vitesse}" + if (s.tenue) " · notes tenues" else "")
    }

    companion object {
        private const val ATTENTE_FIN_MS = 400L

        /** Android refuse un geste de plus de 20 traits (GestureDescription.getMaxStrokeCount). */
        private val MAX_TRAITS = GestureDescription.getMaxStrokeCount().coerceIn(1, Gestes.MAX_TRAITS)

        private const val NOTES_TENUES = "notes_tenues"

        /**
         * Vrai : chaque touche reste enfoncée la durée de sa note (hold_mode « note » du PC), dans la limite
         * de ce qu'un geste peut tenir. Faux (par défaut) : appuis courts de durée fixe.
         */
        fun notesTenues(context: Context): Boolean = Preferences.prefs(context).getBoolean(NOTES_TENUES, false)

        fun definirNotesTenues(context: Context, tenues: Boolean) =
            Preferences.prefs(context).edit().putBoolean(NOTES_TENUES, tenues).apply()
    }
}
