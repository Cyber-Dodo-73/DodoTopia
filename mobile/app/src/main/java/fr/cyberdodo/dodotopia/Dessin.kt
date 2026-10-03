package fr.cyberdodo.dodotopia

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PointF
import android.graphics.Rect
import android.os.Build
import android.os.Handler
import android.os.Looper
import java.io.File
import java.io.IOException
import kotlin.math.max

/**
 * Dessin dans l'outil de peinture d'Heartopia : une image est ramenée à la grille du jeu et à ses couleurs, puis
 * peinte par [Peintre], couleur par couleur.
 *
 * Deux palettes : les 16 pastilles principales (repli sûr, choisi tant que les nuances ne sont pas repérées), ou
 * les 126 nuances du jeu ([Nuancier]). L'outil de peinture mobile a la même disposition que sur PC (toile rayée
 * au centre, palette de 2 × 8 pastilles à droite, outils à gauche) ; les tailles de grille sont celles relevées sur PC.
 */
object Dessin {

    class Format(val nom: String, val largeur: Int, val hauteur: Int)

    /** Nombre de cases à la finesse maximale, par format de toile (DEFAULT_GRIDS de draw.py). */
    val FORMATS = listOf(
        Format("1:1", 150, 150), Format("16:9", 140, 84), Format("4:3", 150, 114),
        Format("3:4", 114, 150), Format("9:16", 84, 150),
    )

    /**
     * Palette principale du jeu : 2 colonnes × 8 lignes, lue de gauche à droite puis de haut en bas.
     * Couleurs lues sur les pastilles de l'outil de peinture mobile (capture du 2026-10-03) ; la couleur
     * réellement déposée sur la toile n'a pas été relevée.
     */
    val PALETTE = intArrayOf(
        0x000202, 0xFDFFFF, 0x373939, 0xEFE9DA, 0xDA282B, 0xF23A19, 0xFD6C0B, 0xF2B00A,
        0x789408, 0x0D7B33, 0x006859, 0x00517D, 0x063A87, 0x2D2F81, 0x5A2365, 0xA02546,
    )
    const val COLONNES_PALETTE = 2
    const val LIGNES_PALETTE = 8

    /**
     * Vrai quand le dessin se fera avec les 126 nuances : l'aperçu et le nombre de couleurs suivent ce choix.
     * Mis à jour par [modeNuances] chaque fois qu'une image est lue ou enregistrée.
     */
    @Volatile
    var nuances = false
        private set

    /**
     * Les nuances servent si l'utilisateur les a demandées, s'il les a repérées dans le jeu et si l'écran peut être
     * relu (Android 11) : sans capture, impossible de savoir quelle page de nuances le jeu affiche.
     */
    fun modeNuances(context: Context): Boolean {
        nuances = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
            Preferences.nuancesVoulues(context) && Preferences.nuancesReperees(context)
        return nuances
    }

    /**
     * Une image prête à peindre. [cases] : pour chaque case, l'indice de sa couleur dans [PALETTE] (16 couleurs).
     * [pixels] : l'image réduite à la grille, avant le choix des couleurs (null pour une image enregistrée par une
     * ancienne version) ; c'est d'elle que sortent les nuances.
     */
    class Travail(val format: String, val largeur: Int, val hauteur: Int, val cases: ByteArray, val pixels: IntArray? = null) {
        private var enNuances: ByteArray? = null

        /** Nombre de couleurs du dessin, dans la palette qui servira. */
        val couleurs: Int get() = couleurs(nuances)

        fun couleurs(avecNuances: Boolean): Int = (if (avecNuances) nuances() else cases).toSet().size

        /** Pour chaque case, sa nuance parmi les 126 ([Nuancier]). */
        fun nuances(): ByteArray {
            enNuances?.let { return it }
            val p = pixels
            val sortie = if (p == null) principales() else ByteArray(p.size) { Nuancier.plusProche(p[it] and 0xFFFFFF).toByte() }
            enNuances = sortie
            return sortie
        }

        /** Les 16 couleurs principales, numérotées comme des nuances. */
        private fun principales(): ByteArray = ByteArray(cases.size) { Nuancier.DE_PRINCIPALE[cases[it].toInt()].toByte() }

        /**
         * Ce que [Peintre] doit peindre : la nuance de chaque case, ou -1 pour une case à laisser vide.
         * Un fond blanc ou crème n'est pas peint : la toile vide du jeu est déjà claire, et le fond représente
         * souvent plus de la moitié des cases.
         */
        fun aPeindre(avecNuances: Boolean): ByteArray {
            val source = if (avecNuances) nuances() else principales()
            val presence = IntArray(Nuancier.TAILLE)
            for (c in source) presence[c.toInt()]++
            val fond = presence.indices.maxByOrNull { presence[it] }
            if (fond != Nuancier.BLANC && fond != Nuancier.CREME) return source
            return ByteArray(source.size) { if (source[it].toInt() == fond) -1 else source[it] }
        }
    }

    /** Recadre l'image au centre selon le format, la réduit à la grille, puis ramène chaque case à la couleur la plus proche. */
    fun convertir(image: Bitmap, format: Format): Travail {
        val rapport = format.largeur.toFloat() / format.hauteur
        var l = image.width
        var h = (l / rapport).toInt()
        if (h > image.height) {
            h = image.height
            l = (h * rapport).toInt()
        }
        val source = Rect((image.width - l) / 2, (image.height - h) / 2, (image.width + l) / 2, (image.height + h) / 2)
        val reduite = Bitmap.createBitmap(format.largeur, format.hauteur, Bitmap.Config.ARGB_8888)
        Canvas(reduite).apply {
            // Fond blanc : une zone transparente de l'image devient du blanc, pas du noir.
            drawColor(Color.WHITE)
            drawBitmap(image, source, Rect(0, 0, format.largeur, format.hauteur), Paint(Paint.FILTER_BITMAP_FLAG))
        }
        val pixels = IntArray(format.largeur * format.hauteur)
        reduite.getPixels(pixels, 0, format.largeur, 0, 0, format.largeur, format.hauteur)
        reduite.recycle()
        return Travail(format.nom, format.largeur, format.hauteur, ByteArray(pixels.size) { plusProche(pixels[it]).toByte() }, pixels)
    }

    /** La pastille principale la plus proche d'une couleur (distance « redmean » de [Nuancier.ecart]). */
    private fun plusProche(couleur: Int): Int {
        var meilleur = 0
        var ecart = Long.MAX_VALUE
        for (k in PALETTE.indices) {
            val d = Nuancier.ecart(couleur and 0xFFFFFF, PALETTE[k])
            if (d < ecart) {
                ecart = d
                meilleur = k
            }
        }
        return meilleur
    }

    /** L'image telle qu'elle sera peinte (16 couleurs ou nuances, selon [nuances]), agrandie sans lissage pour l'aperçu. */
    fun apercu(t: Travail, largeurVoulue: Int): Bitmap {
        val brut = Bitmap.createBitmap(t.largeur, t.hauteur, Bitmap.Config.ARGB_8888)
        val couleurs = if (nuances) {
            val n = t.nuances()
            IntArray(n.size) { Nuancier.COULEURS[n[it].toInt()] or (0xFF shl 24) }
        } else {
            IntArray(t.cases.size) { PALETTE[t.cases[it].toInt()] or (0xFF shl 24) }
        }
        brut.setPixels(couleurs, 0, t.largeur, 0, 0, t.largeur, t.hauteur)
        val echelle = max(1, largeurVoulue / t.largeur)
        return Bitmap.createScaledBitmap(brut, t.largeur * echelle, t.hauteur * echelle, false)
    }

    /** Les traits du crayon pour peindre l'image entière, toutes couleurs confondues (fond clair exclu) : sert à les compter. */
    fun traits(t: Travail): List<PlanDessin.Segment> {
        val cases = t.aPeindre(nuances)
        val sortie = ArrayList<PlanDessin.Segment>()
        for (k in cases.toSet()) {
            if (k < 0) continue
            sortie.addAll(PlanDessin.segments(BooleanArray(cases.size) { cases[it] == k }, t.largeur, t.hauteur))
        }
        return sortie
    }

    /** Centre de la pastille [k] de la palette, entre la première ([premiere]) et la dernière ([derniere]). */
    fun pastille(premiere: PointF, derniere: PointF, k: Int): PointF {
        val colonne = k % COLONNES_PALETTE
        val ligne = k / COLONNES_PALETTE
        return PointF(
            premiere.x + (derniere.x - premiere.x) * colonne / (COLONNES_PALETTE - 1),
            premiere.y + (derniere.y - premiere.y) * ligne / (LIGNES_PALETTE - 1),
        )
    }

    /** Centre de la nuance de rang [rang] (0 à 9) d'une page, entre la première nuance et la dixième. */
    fun nuance(premiere: PointF, derniere: PointF, rang: Int): PointF {
        val colonne = rang % Nuancier.COLONNES
        val ligne = rang / Nuancier.COLONNES
        return PointF(
            premiere.x + (derniere.x - premiere.x) * colonne / (Nuancier.COLONNES - 1),
            premiere.y + (derniere.y - premiere.y) * ligne / (Nuancier.LIGNES - 1),
        )
    }

    private fun fichier(context: Context) = File(context.filesDir, "dessin.bin")

    /**
     * L'image choisie dans l'appli est écrite sur le disque : c'est le service, dans le jeu, qui la peindra.
     * Un octet pour le format (bit 6 levé : l'image réduite suit), les cases, puis trois octets par case.
     */
    fun enregistrer(context: Context, t: Travail) {
        modeNuances(context)
        dernier = null
        val f = FORMATS.indexOfFirst { it.nom == t.format }
        val p = t.pixels
        if (p == null) {
            fichier(context).writeBytes(byteArrayOf(f.toByte()) + t.cases)
            return
        }
        val octets = ByteArray(1 + t.cases.size + 3 * p.size)
        octets[0] = (f or AVEC_PIXELS).toByte()
        t.cases.copyInto(octets, 1)
        var n = 1 + t.cases.size
        for (c in p) {
            octets[n++] = (c shr 16).toByte()
            octets[n++] = (c shr 8).toByte()
            octets[n++] = c.toByte()
        }
        fichier(context).writeBytes(octets)
    }

    fun charger(context: Context): Travail? {
        modeNuances(context)
        // Le menu de la bulle relit l'image à chaque ouverture : tant que le fichier n'a pas changé, on rend la même,
        // avec ses nuances déjà calculées.
        val f = fichier(context)
        val empreinte = f.lastModified() * 31 + f.length()
        dernier?.let { if (empreinte == derniereEmpreinte && f.exists()) return it }
        val t = lire(f) ?: return null
        dernier = t
        derniereEmpreinte = empreinte
        return t
    }

    private var dernier: Travail? = null
    private var derniereEmpreinte = 0L

    private fun lire(f: File): Travail? {
        val octets = try {
            f.readBytes()
        } catch (e: IOException) {
            return null
        }
        val tete = octets.firstOrNull()?.toInt() ?: return null
        val format = FORMATS.getOrNull(tete and AVEC_PIXELS.inv()) ?: return null
        val n = format.largeur * format.hauteur
        if (tete and AVEC_PIXELS == 0) {
            if (octets.size != 1 + n) return null
            return Travail(format.nom, format.largeur, format.hauteur, octets.copyOfRange(1, octets.size))
        }
        if (octets.size != 1 + 4 * n) return null
        val pixels = IntArray(n) {
            val d = 1 + n + 3 * it
            ((octets[d].toInt() and 0xFF) shl 16) or ((octets[d + 1].toInt() and 0xFF) shl 8) or (octets[d + 2].toInt() and 0xFF)
        }
        return Travail(format.nom, format.largeur, format.hauteur, octets.copyOfRange(1, 1 + n), pixels)
    }

    fun oublier(context: Context) {
        fichier(context).delete()
        dernier = null
    }

    private const val AVEC_PIXELS = 0x40
}

/**
 * Envoie des gestes l'un après l'autre : chacun part quand le précédent est terminé, contrairement
 * à la musique où l'heure de chaque note est fixée d'avance. Tout se passe sur le fil principal.
 */
class Traceur(private val service: AccessibilityService) {
    private val principal = Handler(Looper.getMainLooper())
    private var gestes: List<Geste> = emptyList()
    @Volatile
    private var suivant = 0
    private var session = 0
    private var surFin: (() -> Unit)? = null
    var annules = 0
        private set

    val enCours: Boolean get() = surFin != null

    /** Indice du prochain geste à envoyer : la progression, et le point de reprise après une pause. */
    val position: Int get() = suivant

    fun tracer(gestes: List<Geste>, depuis: Int, delaiMs: Long, surFin: () -> Unit) {
        if (enCours) return
        this.gestes = gestes
        this.surFin = surFin
        suivant = depuis.coerceIn(0, gestes.size)
        annules = 0
        val moi = ++session
        principal.postDelayed({ envoyer(moi, false) }, delaiMs)
    }

    /** Arrête et rend l'indice où reprendre. */
    fun arreter(): Int {
        session++
        surFin = null
        principal.removeCallbacksAndMessages(null)
        return suivant
    }

    private fun envoyer(moi: Int, reprise: Boolean) {
        if (moi != session) return
        if (suivant >= gestes.size) {
            val fin = surFin
            surFin = null
            fin?.invoke()
            return
        }
        val g = gestes[suivant]
        val chemin = Path().apply { moveTo(g.x0.coerceAtLeast(0f), g.y0.coerceAtLeast(0f)); lineTo(g.x1.coerceAtLeast(0f), g.y1.coerceAtLeast(0f)) }
        val geste = GestureDescription.Builder().addStroke(GestureDescription.StrokeDescription(chemin, 0, g.dureeMs)).build()
        val retour = object : AccessibilityService.GestureResultCallback() {
            override fun onCompleted(d: GestureDescription?) {
                if (moi != session) return
                suivant++
                principal.postDelayed({ envoyer(moi, false) }, PAUSE_MS + g.pauseMs)
            }

            override fun onCancelled(d: GestureDescription?) {
                if (moi != session) return
                // Un doigt posé sur l'écran annule le geste : on le rejoue une fois, puis on passe au suivant.
                annules++
                if (reprise) suivant++
                principal.postDelayed({ envoyer(moi, !reprise) }, 4 * PAUSE_MS)
            }
        }
        val accepte = try {
            service.dispatchGesture(geste, retour, principal)
        } catch (e: RuntimeException) {
            false
        }
        if (!accepte) {
            suivant++
            principal.postDelayed({ envoyer(moi, false) }, 4 * PAUSE_MS)
        }
    }

    companion object {
        /**
         * Temps doigt levé entre deux gestes. Mesuré dans le jeu le 2026-10-03 : à 25 ms, 40 % des traits
         * étaient perdus (le jeu tourne à 30 images par seconde et ne voyait pas le doigt se lever).
         */
        private const val PAUSE_MS = 90L
    }
}
