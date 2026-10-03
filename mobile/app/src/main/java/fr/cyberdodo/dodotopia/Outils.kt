package fr.cyberdodo.dodotopia

import android.content.Context
import android.content.SharedPreferences
import android.graphics.Color
import android.graphics.Point
import android.graphics.PointF
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
    private const val FICHIER = "dodotopia"
    private const val BULLE = "bulle_active"
    private const val CONFIG = "config_faite"
    private const val DISPOSITION = "disposition"

    fun prefs(context: Context): SharedPreferences = context.getSharedPreferences(FICHIER, Context.MODE_PRIVATE)

    /** Éteinte par défaut : rien ne s'affiche par-dessus le jeu tant qu'on ne l'a pas demandé. */
    fun bulleActive(context: Context): Boolean = prefs(context).getBoolean(BULLE, false)

    fun definirBulle(context: Context, active: Boolean) = prefs(context).edit().putBoolean(BULLE, active).apply()

    /** Vrai une fois l'écran de bienvenue passé. */
    fun configFaite(context: Context): Boolean = prefs(context).getBoolean(CONFIG, false)

    fun definirConfigFaite(context: Context) = prefs(context).edit().putBoolean(CONFIG, true).apply()

    fun disposition(context: Context): Disposition = Dispositions.parId(prefs(context).getString(DISPOSITION, null))

    fun definirDisposition(context: Context, d: Disposition) = prefs(context).edit().putString(DISPOSITION, d.id).apply()

    /** Vrai (par défaut) : rangée grave en bas de l'écran, comme le piano du jeu. « Graves ⇅ » du calibrage l'inverse. */
    fun inverse(context: Context, d: Disposition): Boolean = prefs(context).getBoolean("inverse_${d.id}", true)

    /**
     * Le centre de chaque touche pour l'écran dans son orientation actuelle, ou null si ce clavier
     * n'y a pas été calibré : des positions prises dans une autre orientation viseraient à côté.
     */
    fun touches(context: Context, d: Disposition): List<PointF>? {
        val e = tailleEcran(context)
        val texte = prefs(context).getString("touches_${d.id}_${e.x}x${e.y}", null) ?: return null
        val points = texte.split(';').mapNotNull { morceau ->
            val xy = morceau.split(',')
            val x = xy.getOrNull(0)?.toFloatOrNull()
            val y = xy.getOrNull(1)?.toFloatOrNull()
            if (x == null || y == null) null else PointF(x, y)
        }
        return points.takeIf { it.size == d.notes.size }
    }

    fun definirTouches(context: Context, d: Disposition, points: List<PointF>, inverse: Boolean) {
        val e = tailleEcran(context)
        prefs(context).edit()
            .putString("touches_${d.id}_${e.x}x${e.y}", points.joinToString(";") { "${it.x},${it.y}" })
            .putBoolean("inverse_${d.id}", inverse)
            .apply()
    }

    /** Les quatre repères du dessin (coins de la toile, première et dernière pastille) pour ce format et cet écran. */
    fun reperesDessin(context: Context, format: String): List<PointF>? {
        val e = tailleEcran(context)
        val texte = prefs(context).getString("dessin_${format}_${e.x}x${e.y}", null) ?: return null
        val points = texte.split(';').mapNotNull { morceau ->
            val xy = morceau.split(',')
            val x = xy.getOrNull(0)?.toFloatOrNull()
            val y = xy.getOrNull(1)?.toFloatOrNull()
            if (x == null || y == null) null else PointF(x, y)
        }
        return points.takeIf { it.size == 4 }
    }

    fun definirReperesDessin(context: Context, format: String, points: List<PointF>) {
        val e = tailleEcran(context)
        prefs(context).edit()
            .putString("dessin_${format}_${e.x}x${e.y}", points.joinToString(";") { "${it.x},${it.y}" })
            .apply()
    }

    /** Des points enregistrés sous [cle] pour l'écran dans son orientation actuelle, s'il y en a bien [nombre]. */
    private fun points(context: Context, cle: String, nombre: Int): List<PointF>? {
        val e = tailleEcran(context)
        val texte = prefs(context).getString("${cle}_${e.x}x${e.y}", null) ?: return null
        val points = texte.split(';').mapNotNull { morceau ->
            val xy = morceau.split(',')
            val x = xy.getOrNull(0)?.toFloatOrNull()
            val y = xy.getOrNull(1)?.toFloatOrNull()
            if (x == null || y == null) null else PointF(x, y)
        }
        return points.takeIf { it.size == nombre }
    }

    private fun definirPoints(context: Context, cle: String, points: List<PointF>) {
        val e = tailleEcran(context)
        prefs(context).edit().putString("${cle}_${e.x}x${e.y}", points.joinToString(";") { "${it.x},${it.y}" }).apply()
    }

    /**
     * Les six repères des nuances du dessin : bouton « palette », bouton retour, flèches précédent et suivant,
     * première et dixième nuance. Les mêmes pour tous les formats de toile.
     */
    fun reperesNuances(context: Context): List<PointF>? = points(context, "dessin_nuances", 6)

    fun definirReperesNuances(context: Context, points: List<PointF>) = definirPoints(context, "dessin_nuances", points)

    /** Les trois outils du dessin : crayon, pot de peinture, bouton Annuler. */
    fun reperesOutils(context: Context): List<PointF>? = points(context, "dessin_outils", 3)

    fun definirReperesOutils(context: Context, points: List<PointF>) = definirPoints(context, "dessin_outils", points)

    /** Vrai si les nuances ont été repérées, quelle que soit l'orientation (l'appli est en portrait, le jeu en paysage). */
    fun nuancesReperees(context: Context): Boolean = prefs(context).all.keys.any { it.startsWith("dessin_nuances_") }

    /** Dessiner avec les 126 nuances plutôt qu'avec les 16 couleurs principales. Éteint par défaut : les 16 couleurs sont le repli sûr. */
    fun nuancesVoulues(context: Context): Boolean = prefs(context).getBoolean("dessin_nuances", false)

    fun definirNuancesVoulues(context: Context, oui: Boolean) = prefs(context).edit().putBoolean("dessin_nuances", oui).apply()

    /** Remplir les grandes zones au pot de peinture (mode contours). Éteint par défaut : jamais essayé dans le jeu mobile. */
    fun potVoulu(context: Context): Boolean = prefs(context).getBoolean("dessin_pot", false)

    fun definirPotVoulu(context: Context, oui: Boolean) = prefs(context).edit().putBoolean("dessin_pot", oui).apply()

    /** Cuisine : servir toutes les cuisinières visibles. Éteint par défaut : une seule, celle devant laquelle on se tient. */
    fun plusieursCuisinieres(context: Context): Boolean = prefs(context).getBoolean("cuisine_plusieurs", false)

    fun definirPlusieursCuisinieres(context: Context, oui: Boolean) = prefs(context).edit().putBoolean("cuisine_plusieurs", oui).apply()

    /** Vrai si ce clavier a été calibré, quelle que soit l'orientation (l'appli est en portrait, le jeu en paysage). */
    fun calibre(context: Context, d: Disposition): Boolean =
        prefs(context).all.keys.any { it.startsWith("touches_${d.id}_") }
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

/** 125 000 ms donne « 2:05 ». */
fun minutes(ms: Long): String {
    val s = (ms / 1000).toInt()
    return String.format(Locale.ROOT, "%d:%02d", s / 60, s % 60)
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
