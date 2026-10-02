package fr.cyberdodo.dodotopia

import android.content.Context
import android.graphics.Color
import android.graphics.Point
import android.hardware.display.DisplayManager
import android.view.Display
import androidx.lifecycle.MutableLiveData
import java.util.Locale
import kotlin.math.ceil
import kotlin.math.sqrt

/** Résultats affichés dans l'activité, alimentés par les services. */
object Resultats {
    val capture = MutableLiveData<String>()
    val metronome = MutableLiveData<String>()
}

/** Choix de l'utilisateur partagés entre l'activité et le service (même processus, même fichier). */
object Preferences {
    const val FICHIER = "etape1"
    private const val BULLE = "bulle_active"
    private const val CONFIG = "config_faite"

    private fun prefs(context: Context) = context.getSharedPreferences(FICHIER, Context.MODE_PRIVATE)

    /** Éteinte par défaut : rien ne s'affiche par-dessus le jeu tant qu'on ne l'a pas demandé. */
    fun bulleActive(context: Context): Boolean = prefs(context).getBoolean(BULLE, false)

    fun definirBulle(context: Context, active: Boolean) = prefs(context).edit().putBoolean(BULLE, active).apply()

    /** Vrai une fois l'écran « Avant de commencer » passé. */
    fun configFaite(context: Context): Boolean = prefs(context).getBoolean(CONFIG, false)

    fun definirConfigFaite(context: Context) = prefs(context).edit().putBoolean(CONFIG, true).apply()
}

/**
 * Taille réelle de l'écran dans son orientation actuelle (barres système comprises).
 * getRealSize est déprécié mais reste le seul appel valable depuis un service sur toutes les versions,
 * là où currentWindowMetrics réclame un contexte d'interface.
 */
@Suppress("DEPRECATION")
fun tailleEcran(context: Context): Point {
    val ecran = context.getSystemService(DisplayManager::class.java).getDisplay(Display.DEFAULT_DISPLAY)
    return Point().also { ecran.getRealSize(it) }
}

/** Luminosité perçue 0..255 d'une couleur ARGB. 0 partout = fenêtre protégée (FLAG_SECURE). */
fun luminosite(couleur: Int): Int =
    (Color.red(couleur) * 299 + Color.green(couleur) * 587 + Color.blue(couleur) * 114) / 1000

fun luminosite(r: Int, v: Int, b: Int): Int = (r * 299 + v * 587 + b * 114) / 1000

/** Moyenne, p95 (rang le plus proche), max et écart-type d'une série de mesures en millisecondes. */
class Serie(valeurs: List<Double>) {
    val n = valeurs.size
    val moyenne: Double
    val p95: Double
    val max: Double
    val ecartType: Double

    init {
        if (n == 0) {
            moyenne = Double.NaN; p95 = Double.NaN; max = Double.NaN; ecartType = Double.NaN
        } else {
            val tri = valeurs.sorted()
            moyenne = tri.average()
            p95 = tri[(ceil(0.95 * n).toInt() - 1).coerceIn(0, n - 1)]
            max = tri.last()
            ecartType = sqrt(tri.sumOf { (it - moyenne) * (it - moyenne) } / n)
        }
    }

    override fun toString(): String =
        if (n == 0) "aucune mesure"
        else String.format(Locale.FRANCE, "moy %.1f · p95 %.1f · max %.1f ms", moyenne, p95, max)
}
