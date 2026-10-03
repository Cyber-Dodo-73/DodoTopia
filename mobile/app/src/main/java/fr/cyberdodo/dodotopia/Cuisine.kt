package fr.cyberdodo.dodotopia

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.Display
import java.util.concurrent.Executors

/**
 * Cuisine automatique : regarde l'écran, reconnaît les bulles des cuisinières et appuie dessus au bon moment.
 *
 * Ici : les captures et les appuis. La reconnaissance est dans [CuisineVue] (menu des recettes, dialogue du plat
 * amélioré, bulles poêle / gants / feu à ajuster / minuteur) et les décisions dans [CuisineBoucle] ; ces deux-là
 * n'ont pas besoin d'Android et sont rejouées hors appareil sur des captures du jeu.
 *
 * Les captures passent par le service d'accessibilité (Android 11 minimum), une par seconde au mieux sur
 * Android 11, trois sur les versions suivantes.
 */
class Cuisine(private val service: AccessibilityService) {

    private val principal = Handler(Looper.getMainLooper())
    private val analyse = Executors.newSingleThreadExecutor()
    private var session = 0
    private var surArret: ((Int) -> Unit)? = null
    private var boucle: CuisineBoucle? = null

    /** Les pixels de la dernière capture : le tableau ressert d'une capture à l'autre (fil d'analyse seulement). */
    private var tampon = IntArray(0)

    val plats: Int get() = boucle?.plats ?: 0
    val feux: Int get() = boucle?.feux ?: 0

    val enCours: Boolean get() = surArret != null

    /**
     * [plusieurs] : servir toutes les cuisinières visibles, et pas seulement celle devant laquelle on se tient.
     * [surArret] reçoit la raison quand la cuisine s'arrête d'elle-même (identifiant de texte).
     */
    fun demarrer(plusieurs: Boolean, surArret: (Int) -> Unit) {
        if (enCours) return
        this.surArret = surArret
        boucle = CuisineBoucle(plusieurs, INTERVALLE_MS) { SpikeLog.log("Cuisine : $it") }
        val moi = ++session
        SpikeLog.log("Cuisine : départ · " + if (plusieurs) "plusieurs cuisinières" else "une cuisinière")
        principal.postDelayed({ regarder(moi, plusieurs) }, 800)
    }

    fun arreter() {
        if (!enCours) return
        session++
        surArret = null
        principal.removeCallbacksAndMessages(null)
        SpikeLog.log("Cuisine : arrêt · $plats plats · $feux feux ajustés")
    }

    private fun finir(raison: Int) {
        val fin = surArret
        arreter()
        fin?.invoke(raison)
    }

    private fun regarder(moi: Int, large: Boolean) {
        if (moi != session || Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return
        val demande = SystemClock.uptimeMillis()
        // La prochaine capture part INTERVALLE_MS après la demande de celle-ci, quel que soit le temps de son analyse.
        fun suivante() = principal.postAtTime({ regarder(moi, large) }, demande + INTERVALLE_MS)
        service.takeScreenshot(Display.DEFAULT_DISPLAY, analyse, object : AccessibilityService.TakeScreenshotCallback {
            override fun onSuccess(resultat: AccessibilityService.ScreenshotResult) {
                val materiel = resultat.hardwareBuffer
                val image = Bitmap.wrapHardwareBuffer(materiel, resultat.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
                materiel.close()
                val lecture = if (image == null) null else lire(image, large).also { image.recycle() }
                principal.post {
                    if (moi != session) return@post
                    if (lecture != null) agir(lecture)
                    if (moi == session) suivante()
                }
            }

            override fun onFailure(code: Int) {
                // Captures trop rapprochées ou écran protégé : on réessaie au tour suivant.
                principal.post { suivante() }
            }
        })
    }

    private fun lire(image: Bitmap, large: Boolean): CuisineVue.Lecture {
        val l = image.width
        val h = image.height
        if (tampon.size != l * h) tampon = IntArray(l * h)
        image.getPixels(tampon, 0, l, 0, 0, l, h)
        return CuisineVue.lire(tampon, l, h, large)
    }

    private fun agir(v: CuisineVue.Lecture) {
        val decision = boucle?.decider(v, SystemClock.uptimeMillis()) ?: return
        when (decision.fin) {
            CuisineBoucle.Fin.INGREDIENTS -> finir(R.string.cuisine_ingredients)
            CuisineBoucle.Fin.FEU_BLOQUE -> finir(R.string.cuisine_feu_bloque)
            CuisineBoucle.Fin.PERDUE -> finir(R.string.cuisine_perdue)
            null -> for (a in decision.appuis) {
                if (a.delaiMs <= 0) appuyer(a.x, a.y) else principal.postDelayed({ if (enCours) appuyer(a.x, a.y) }, a.delaiMs)
            }
        }
    }

    private fun appuyer(x: Float, y: Float) {
        val chemin = Path().apply { moveTo(x, y); lineTo(x, y) }
        val geste = GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(chemin, 0, APPUI_MS)).build()
        try {
            service.dispatchGesture(geste, null, null)
        } catch (e: RuntimeException) {
            // Service en cours d'arrêt.
        }
    }

    companion object {
        private const val APPUI_MS = 90L

        /** Android 11 refuse plus d'une capture par seconde ; les versions suivantes en acceptent trois. */
        private val INTERVALLE_MS = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) 400L else 1010L
    }
}
