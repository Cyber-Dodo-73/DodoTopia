package fr.cyberdodo.dodotopia

import android.accessibilityservice.AccessibilityService
import android.content.Context
import android.graphics.Bitmap
import android.graphics.PointF
import android.graphics.Rect
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Base64
import android.view.Display
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.util.BitSet
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executor
import java.util.concurrent.TimeUnit

/**
 * Peint une image dans l'outil de peinture du jeu. Les étapes du dessin sont dans [Etapes] (sans Android) ; ici,
 * ce qu'elles demandent à l'appareil : envoyer les gestes par [Traceur], capturer l'écran par le service, et tenir
 * sur le disque le compte des cases peintes pour reprendre un dessin interrompu (`dessin_reprise.json`, comme sur PC).
 *
 * Le dessin se déroule sur un fil à part, écrit comme une suite d'étapes qui attendent chacune la fin de la
 * précédente ; les gestes et les captures, eux, passent par le fil principal.
 */
class Peintre(private val service: DodoAccessibilityService) : Atelier {

    /**
     * Où agir dans le jeu (voir [Etapes.Reperes]). [masques] : nos propres fenêtres, que les captures montrent
     * par-dessus le jeu ; ce qu'elles cachent n'est pas relu.
     */
    class Reperes(
        val toile0: PointF, val toile1: PointF, val palette0: PointF, val palette1: PointF,
        val nuances: List<PointF>?, val outils: List<PointF>?, val masques: List<Rect>,
    )

    /** Comment le dessin s'est terminé. [erreur] : 0, ou le texte qui explique pourquoi il s'est arrêté de lui-même. */
    class Bilan(val erreur: Int, val retouchees: Int, val manquantes: Int, val zones: Int, val fuites: Int)

    private class Arret : RuntimeException()

    private val principal = Handler(Looper.getMainLooper())
    private val direct = Executor { it.run() }

    @Volatile
    private var fil: Thread? = null

    @Volatile
    private var arret = false

    @Volatile
    private var etapes: Etapes? = null

    val enCours: Boolean get() = fil != null

    /** Où en est le dessin : phase, couleur en cours… null avant le premier dessin. */
    val etat: Etapes? get() = etapes

    /** Nombre de cases à peindre. */
    @Volatile
    var total = 1
        private set

    private var cle = ""
    private var masques: List<Rect> = emptyList()
    private var derniereCapture = 0L

    /** Cases déjà peintes. Protégé par son propre verrou, comme [lot], [lotNote] et [termine]. */
    private val faites = BitSet()
    private var termine = false

    /** Les cases que peint chaque geste du lot en cours, et le nombre de gestes déjà comptés. */
    private var lot: List<IntArray?>? = null
    private var lotNote = 0

    @Volatile
    private var lotLance = false

    /** Nombre de cases peintes jusqu'ici. À appeler depuis le fil principal. */
    fun avancement(): Int {
        if (lotLance) noter(service.traceur.position)
        return synchronized(faites) { faites.cardinality() }
    }

    /**
     * Peint [t]. [reprendre] : repart des cases déjà peintes d'un dessin interrompu, si le fichier de reprise est
     * celui de cette image. [surFin] n'est appelé que si le dessin s'arrête de lui-même (fini, ou erreur).
     */
    fun demarrer(
        t: Dessin.Travail, avecNuances: Boolean, avecPot: Boolean, caseMs: Int, reperes: Reperes, reprendre: Boolean,
        surFin: (Bilan) -> Unit,
    ) {
        if (enCours) return
        val cases = t.aPeindre(avecNuances)
        cle = cle(t, avecNuances)
        masques = reperes.masques
        val dejaFaites = BooleanArray(cases.size)
        synchronized(faites) {
            faites.clear()
            lot = null
            termine = false
            if (reprendre) lireReprise(service, cle)?.let { faites.or(it) }
            for (n in cases.indices) dejaFaites[n] = faites.get(n)
        }
        total = cases.count { it >= 0 }.coerceAtLeast(1)
        fun point(p: PointF) = PointEcran(p.x, p.y)
        val e = Etapes(
            cases, t.largeur, t.hauteur, avecNuances, avecPot, caseMs,
            Etapes.Reperes(
                point(reperes.toile0), point(reperes.toile1), point(reperes.palette0), point(reperes.palette1),
                reperes.nuances?.map(::point), reperes.outils?.map(::point),
            ),
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.R, this,
        )
        etapes = e
        arret = false
        lotLance = false
        val moi = Thread({ travail(e, dejaFaites, surFin) }, "dessin")
        fil = moi
        moi.start()
    }

    /** Arrête le dessin et enregistre où il en est, pour le reprendre plus tard. À appeler depuis le fil principal. */
    fun arreter() {
        val f = fil ?: return
        arret = true
        fil = null
        val position = service.traceur.arreter()
        if (lotLance) noter(position)
        lotLance = false
        ecrireReprise()
        f.interrupt()
    }

    private fun travail(e: Etapes, dejaFaites: BooleanArray, surFin: (Bilan) -> Unit) {
        val moi = Thread.currentThread()
        val bilan = try {
            // Laisse le menu se replier avant le premier geste.
            attendre(DELAI_DEPART_MS)
            val manquantes = e.peindre(dejaFaites)
            SpikeLog.log("Dessin : ${service.traceur.annules} gestes annulés au dernier lot")
            Bilan(0, e.retouchees, manquantes, e.zonesRemplies, e.fuites)
        } catch (ex: Arret) {
            return
        } catch (ex: Etapes.NuancesIllisibles) {
            Bilan(R.string.dessin_nuances_illisibles, e.retouchees, 0, e.zonesRemplies, e.fuites)
        } catch (ex: RuntimeException) {
            SpikeLog.log("Dessin : erreur inattendue · $ex")
            Bilan(R.string.dessin_erreur, e.retouchees, 0, e.zonesRemplies, e.fuites)
        }
        if (bilan.erreur == 0) {
            synchronized(faites) { termine = true }
            oublierReprise(service)
        } else {
            ecrireReprise()
        }
        principal.post {
            if (fil === moi) {
                fil = null
                surFin(bilan)
            }
        }
    }

    // ------------------------------------------------------------------ ce que demandent les étapes

    override fun tracer(gestes: List<Geste>, peintes: List<IntArray?>?) {
        if (gestes.isEmpty()) return
        verifierArret()
        val fini = CountDownLatch(1)
        synchronized(faites) {
            lot = peintes
            lotNote = 0
        }
        principal.post {
            if (arret) {
                fini.countDown()
            } else {
                service.traceur.tracer(gestes, 0, 0) { fini.countDown() }
                lotLance = true
            }
        }
        try {
            while (!fini.await(SAUVEGARDE_MS, TimeUnit.MILLISECONDS)) {
                if (peintes != null && lotLance) {
                    noter(service.traceur.position)
                    ecrireReprise()
                }
            }
        } catch (e: InterruptedException) {
            throw Arret()
        }
        verifierArret()
        noter(gestes.size)
        lotLance = false
        synchronized(faites) { lot = null }
    }

    /** Une capture de l'écran, ou null. Respecte la limite du système : une par seconde sur Android 11, trois ensuite. */
    override fun capturer(): Capture? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        for (essai in 0..1) {
            attendre(derniereCapture + INTERVALLE_MS - SystemClock.uptimeMillis())
            derniereCapture = SystemClock.uptimeMillis()
            val recue = CountDownLatch(1)
            var image: Bitmap? = null
            service.takeScreenshot(Display.DEFAULT_DISPLAY, direct, object : AccessibilityService.TakeScreenshotCallback {
                override fun onSuccess(resultat: AccessibilityService.ScreenshotResult) {
                    val tampon = resultat.hardwareBuffer
                    image = Bitmap.wrapHardwareBuffer(tampon, resultat.colorSpace)?.copy(Bitmap.Config.ARGB_8888, false)
                    tampon.close()
                    recue.countDown()
                }

                override fun onFailure(code: Int) {
                    SpikeLog.log("Dessin : capture refusée (code $code)")
                    recue.countDown()
                }
            })
            try {
                recue.await(4, TimeUnit.SECONDS)
            } catch (e: InterruptedException) {
                throw Arret()
            }
            verifierArret()
            val recu = image
            if (recu != null) return Ecran(recu, masques)
        }
        return null
    }

    private class Ecran(private val image: Bitmap, private val masques: List<Rect>) : Capture {
        override fun couleur(x: Int, y: Int): Int {
            if (x < 0 || y < 0 || x >= image.width || y >= image.height) return -1
            for (m in masques) if (m.contains(x, y)) return -1
            return image.getPixel(x, y) and 0xFFFFFF
        }

        override fun fermer() = image.recycle()
    }

    override fun attendre(ms: Long) {
        verifierArret()
        if (ms <= 0) return
        try {
            Thread.sleep(ms)
        } catch (e: InterruptedException) {
            throw Arret()
        }
        verifierArret()
    }

    override fun marquer(cases: IntArray) {
        synchronized(faites) { for (n in cases) faites.set(n) }
        ecrireReprise()
    }

    override fun toutOublier() {
        synchronized(faites) { faites.clear() }
        oublierReprise(service)
    }

    override fun journal(texte: String) = SpikeLog.log("Dessin : $texte")

    /** Les [position] premiers gestes du lot en cours sont partis : leurs cases sont peintes. */
    private fun noter(position: Int) {
        synchronized(faites) {
            val peintes = lot ?: return
            for (g in lotNote until position.coerceAtMost(peintes.size)) peintes[g]?.forEach { faites.set(it) }
            if (position > lotNote) lotNote = position
        }
    }

    private fun verifierArret() {
        if (arret) throw Arret()
    }

    // ------------------------------------------------------------------ reprise après fermeture

    /** Écrit les cases déjà peintes sur le disque. Rien une fois le dessin fini. */
    private fun ecrireReprise() {
        synchronized(faites) {
            if (termine || faites.isEmpty) return
            try {
                val json = JSONObject()
                    .put("version", VERSION_REPRISE)
                    .put("cle", cle)
                    .put("total", total)
                    .put("nombre", faites.cardinality())
                    .put("faites", Base64.encodeToString(faites.toByteArray(), Base64.NO_WRAP))
                    .put("date", System.currentTimeMillis())
                val provisoire = File(service.filesDir, "$FICHIER_REPRISE.tmp")
                provisoire.writeText(json.toString())
                if (!provisoire.renameTo(fichierReprise(service))) {
                    fichierReprise(service).delete()
                    provisoire.renameTo(fichierReprise(service))
                }
            } catch (e: IOException) {
                SpikeLog.log("Dessin : fichier de reprise non enregistré · ${e.message}")
            } catch (e: JSONException) {
                SpikeLog.log("Dessin : fichier de reprise non enregistré · ${e.message}")
            }
        }
    }

    companion object {
        private const val FICHIER_REPRISE = "dessin_reprise.json"
        private const val VERSION_REPRISE = 1

        /** Laisse le menu se replier avant le premier geste. */
        private const val DELAI_DEPART_MS = 1500L

        /** Android 11 refuse plus d'une capture par seconde ; les versions suivantes en acceptent trois. */
        private val INTERVALLE_MS = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) 350L else 1010L

        /** Pendant un long lot de traits, les cases peintes sont écrites sur le disque toutes les deux secondes (comme sur PC). */
        private const val SAUVEGARDE_MS = 2000L

        private fun fichierReprise(context: Context) = File(context.filesDir, FICHIER_REPRISE)

        /** Empreinte d'un dessin : même format, mêmes cases, même palette. */
        fun cle(t: Dessin.Travail, avecNuances: Boolean): String =
            "${t.format}:${if (avecNuances) 126 else 16}:${t.aPeindre(avecNuances).contentHashCode()}"

        private fun lireReprise(context: Context, cle: String): BitSet? {
            return try {
                val json = JSONObject(fichierReprise(context).readText())
                if (json.getInt("version") != VERSION_REPRISE || json.getString("cle") != cle) return null
                BitSet.valueOf(Base64.decode(json.getString("faites"), Base64.NO_WRAP))
            } catch (e: IOException) {
                null
            } catch (e: JSONException) {
                null
            } catch (e: IllegalArgumentException) {
                null
            }
        }

        /** Part déjà peinte (0 à 100) du dessin [cle] interrompu, ou null s'il n'y a rien à reprendre pour cette image. */
        fun reprise(context: Context, cle: String): Int? {
            return try {
                val json = JSONObject(fichierReprise(context).readText())
                if (json.getInt("version") != VERSION_REPRISE || json.getString("cle") != cle) return null
                val nombre = json.getInt("nombre")
                if (nombre <= 0) null else (100L * nombre / json.getInt("total").coerceAtLeast(1)).toInt().coerceIn(0, 100)
            } catch (e: IOException) {
                null
            } catch (e: JSONException) {
                null
            }
        }

        fun oublierReprise(context: Context) {
            fichierReprise(context).delete()
        }
    }
}
