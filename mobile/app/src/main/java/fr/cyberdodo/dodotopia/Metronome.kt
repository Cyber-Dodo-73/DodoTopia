package fr.cyberdodo.dodotopia

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Path
import android.graphics.PointF
import android.os.Handler
import android.os.HandlerThread
import android.os.Looper
import android.os.Process
import android.os.SystemClock
import java.util.Locale
import kotlin.math.roundToLong

data class Reglages(
    val bpm: Int,
    val appuis: Int,
    val accord: Boolean,
    val dureeMs: Long,
    val reperes: List<PointF>,
)

/**
 * Envoie des appuis à cadence fixe et mesure ce que le système en fait.
 *
 * Tout le temps réel vit sur un fil dédié : programmation par postAtTime, envoi, et retours de
 * dispatchGesture (on passe notre Handler pour que le fil principal, occupé par les fenêtres,
 * ne fausse pas le délai mesuré). C'est le même schéma que le futur PlaybackEngine.
 */
class Metronome(private val service: AccessibilityService) {

    private class Mesure(val reglages: Reglages) {
        val n = reglages.appuis
        val prevuNs = LongArray(n)
        val envoiNs = LongArray(n)
        val retardMs = DoubleArray(n) { Double.NaN }
        val delaiMs = DoubleArray(n) { Double.NaN }
        val etat = IntArray(n) { NON_ENVOYE }
    }

    private val fil = HandlerThread("DodoMetronome", Process.THREAD_PRIORITY_URGENT_AUDIO).apply { start() }
    private val handler = Handler(fil.looper)
    private val principal = Handler(Looper.getMainLooper())

    @Volatile
    private var mesure: Mesure? = null

    val enCours: Boolean get() = mesure != null

    /**
     * [surFin] est appelé sur le fil principal avec le résumé, que la mesure aille au bout ou soit arrêtée.
     * [surAppui] l'est aussi, après chaque envoi, avec le nombre d'appuis partis : il ne sert qu'à l'affichage.
     */
    fun lancer(reglages: Reglages, surAppui: (Int) -> Unit, surFin: (String) -> Unit) {
        if (enCours || reglages.reperes.isEmpty()) return
        val m = Mesure(reglages)
        mesure = m
        handler.post {
            // Les deux horloges sont monotones et s'arrêtent ensemble en veille : uptimeMillis programme,
            // nanoTime mesure. On les lit au même instant pour passer de l'une à l'autre.
            val maintenantMs = SystemClock.uptimeMillis()
            val maintenantNs = System.nanoTime()
            val t0 = maintenantMs + DELAI_DEPART_MS
            var dernier = t0
            for (i in 0 until m.n) {
                val quand = t0 + (i * 60000.0 / reglages.bpm).roundToLong()
                m.prevuNs[i] = maintenantNs + (quand - maintenantMs) * 1_000_000
                handler.postAtTime({
                    appuyer(m, i)
                    principal.post { if (mesure === m) surAppui(i + 1) }
                }, m, quand)
                dernier = quand
            }
            handler.postAtTime({ finir(m, false, surFin) }, m, dernier + reglages.dureeMs + ATTENTE_FIN_MS)
        }
    }

    /** Arrêt d'urgence (volume bas, bulle). Appelable de n'importe quel fil. */
    fun arreter(surFin: (String) -> Unit) {
        val m = mesure ?: return
        handler.removeCallbacksAndMessages(m)
        handler.post { finir(m, true, surFin) }
    }

    fun fermer() {
        mesure = null
        fil.quitSafely()
    }

    private fun appuyer(m: Mesure, i: Int) {
        m.retardMs[i] = (System.nanoTime() - m.prevuNs[i]) / 1e6
        val r = m.reglages
        val geste = GestureDescription.Builder()
        // Accord : un trait par repère dans le même geste, donc autant de doigts posés au même instant.
        val cibles = if (r.accord) r.reperes.take(MAX_DOIGTS) else listOf(r.reperes[i % r.reperes.size])
        for (p in cibles) {
            val x = p.x.coerceAtLeast(0f)
            val y = p.y.coerceAtLeast(0f)
            val trait = Path().apply { moveTo(x, y); lineTo(x, y) }
            geste.addStroke(GestureDescription.StrokeDescription(trait, 0, r.dureeMs))
        }
        val retour = object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(g: GestureDescription?) {
                // De l'envoi à la fin du geste, durée du geste déduite : ce que le système ajoute.
                m.delaiMs[i] = (System.nanoTime() - m.envoiNs[i]) / 1e6 - r.dureeMs
                m.etat[i] = TERMINE
            }

            override fun onCancelled(g: GestureDescription?) {
                m.etat[i] = ANNULE
            }
        }
        m.envoiNs[i] = System.nanoTime()
        val accepte = try {
            service.dispatchGesture(geste.build(), retour, handler)
        } catch (e: RuntimeException) {
            false
        }
        m.etat[i] = if (accepte) ENVOYE else REFUSE
    }

    private fun finir(m: Mesure, arrete: Boolean, surFin: (String) -> Unit) {
        if (mesure !== m) return
        mesure = null
        val resume = resumer(m, arrete)
        SpikeLog.log(resume + "\n" + detail(m))
        principal.post { surFin(resume) }
    }

    private fun resumer(m: Mesure, arrete: Boolean): String {
        val r = m.reglages
        val envoyes = m.etat.count { it != NON_ENVOYE }
        // Le tout premier geste paie la mise en route du système (constaté : plus de 100 ms, puis 2 ms).
        // Il reste dans le détail du journal mais sort des statistiques, sinon il décide seul du p95.
        val froid = if (envoyes >= MIN_POUR_EXCLURE) 1 else 0
        val retard = Serie(m.retardMs.drop(froid).filter { !it.isNaN() })
        val delai = Serie(m.delaiMs.drop(froid).filter { !it.isNaN() })
        val gigue = if (delai.n == 0) "" else String.format(Locale.FRANCE, " (gigue %.1f)", delai.ecartType)
        val doigts = if (r.accord) minOf(r.reperes.size, MAX_DOIGTS) else 1
        return buildString {
            append("Métronome ${r.bpm} bpm · $envoyes/${m.n} appuis · ${r.dureeMs} ms · ")
            append(if (r.accord) "accord de $doigts" else "${r.reperes.size} repère(s) à tour de rôle")
            if (arrete) append(" · ARRÊTÉ")
            append("\nRetard d'envoi : $retard")
            append("\nDélai système : $delai$gigue")
            if (froid == 1 && !m.delaiMs[0].isNaN()) {
                append(String.format(Locale.FRANCE, "\n1er appui hors statistiques : délai %.1f ms", m.delaiMs[0]))
            }
            append("\nTerminés ${m.etat.count { it == TERMINE }}")
            append(" · annulés ${m.etat.count { it == ANNULE }}")
            append(" · refusés ${m.etat.count { it == REFUSE }}")
            append(" · sans réponse ${m.etat.count { it == ENVOYE }}")
            append("\n" + verdict(retard, delai))
        }
    }

    /** Lecture des seuils du brief (PROMPT-mobile.md, critères de validation). Indicatif : l'oreille tranche. */
    private fun verdict(retard: Serie, delai: Serie): String = when {
        delai.n == 0 -> "Verdict : aucun geste terminé, rien à conclure."
        delai.p95 > 120 || delai.ecartType > 40 -> "Verdict : trop lent ou trop irrégulier, piste Shizuku."
        delai.p95 >= 60 -> "Verdict : jouable avec compensation de latence."
        retard.p95 >= 15 -> "Verdict : délai système bon, mais envoi en retard (téléphone chargé ?)."
        else -> "Verdict : bon pour la musique."
    }

    private fun detail(m: Mesure): String = buildString {
        append("  n° ; retard d'envoi ms ; délai système ms ; état")
        for (i in 0 until m.n) {
            if (m.etat[i] == NON_ENVOYE) continue
            append(String.format(Locale.ROOT, "\n  %d ; %.2f ; %.2f ; %s", i + 1, m.retardMs[i], m.delaiMs[i], NOMS[m.etat[i]]))
        }
    }

    companion object {
        const val MAX_DOIGTS = 10

        /** Laisse le panneau se replier avant le premier appui. */
        private const val DELAI_DEPART_MS = 1500L

        /** Laisse revenir les derniers retours avant de compter. */
        private const val ATTENTE_FIN_MS = 800L

        /** En dessous, la série est trop courte pour se permettre d'en écarter un appui. */
        private const val MIN_POUR_EXCLURE = 8

        private const val NON_ENVOYE = 0
        private const val ENVOYE = 1
        private const val TERMINE = 2
        private const val ANNULE = 3
        private const val REFUSE = 4
        private val NOMS = arrayOf("non envoyé", "sans réponse", "terminé", "annulé", "refusé")
    }
}
