package fr.cyberdodo.dodotopia

import kotlin.math.abs

/** Un geste du dessin : un appui (départ = arrivée) ou un trait droit. [pauseMs] s'ajoute au temps doigt levé qui le suit. */
class Geste(val x0: Float, val y0: Float, val x1: Float, val y1: Float, val dureeMs: Long, val pauseMs: Long = 0)

/** Un point de l'écran. */
class PointEcran(val x: Float, val y: Float)

/** Une capture d'écran : la couleur d'un pixel (0xRRGGBB), ou -1 s'il est hors de l'écran ou caché par une de nos fenêtres. */
interface Capture {
    fun couleur(x: Int, y: Int): Int
    fun fermer()
}

/** Ce que les étapes du dessin demandent au monde extérieur : le jeu sur l'appareil, ou un faux jeu pour les essais. */
interface Atelier {
    /** Envoie les gestes et attend le dernier. [peintes] : les cases que peint chaque geste, pour l'avancement et la reprise. */
    fun tracer(gestes: List<Geste>, peintes: List<IntArray?>? = null)

    /** Une capture de l'écran, ou null s'il ne peut pas être regardé maintenant. */
    fun capturer(): Capture?

    fun attendre(ms: Long)

    /** Ces cases sont peintes (coup de pot réussi). */
    fun marquer(cases: IntArray)

    /** La toile a été vidée depuis l'arrêt : plus aucune case n'est peinte. */
    fun toutOublier()

    fun journal(texte: String)
}

/**
 * Les étapes d'un dessin, comme `Drawer._paint` de draw.py sur PC : couleur par couleur, avec relecture de la toile
 * après chaque couleur (les cases manquées sont repeintes) et, si on le demande, pot de peinture pour le fond et
 * les grandes zones. Sans Android : les gestes et les captures passent par [Atelier], ce qui permet de dérouler un
 * dessin entier hors appareil, face à un faux jeu.
 *
 * Jamais essayé dans le jeu à ce jour (2026-10-03) : nuances, pot de peinture, traits verticaux et relecture par
 * couleur reposent sur ce qu'on sait de la version PC et sur une capture de l'outil mobile.
 */
class Etapes(
    /** La nuance de chaque case, ou -1 pour une case à laisser vide. */
    private val cases: ByteArray,
    private val largeur: Int,
    private val hauteur: Int,
    private val avecNuances: Boolean,
    private val avecPot: Boolean,
    /** Durée ajoutée à un trait par case traversée. */
    private val caseMs: Int,
    private val r: Reperes,
    /** Vrai si l'écran peut être regardé (Android 11). */
    private val voir: Boolean,
    private val atelier: Atelier,
) {
    enum class Phase { PEINTURE, VERIFICATION, RETOUCHES, REMPLISSAGE }

    /**
     * Où agir dans le jeu. [nuances] : bouton « palette », bouton retour, flèches précédent et suivant, première et
     * dixième nuance. [outils] : crayon, pot de peinture, Annuler.
     */
    class Reperes(
        val toile0: PointEcran, val toile1: PointEcran, val palette0: PointEcran, val palette1: PointEcran,
        val nuances: List<PointEcran>?, val outils: List<PointEcran>?,
    )

    /** Le dessin ne peut pas continuer : la page des nuances ne se lit pas. */
    class NuancesIllisibles : RuntimeException()

    @Volatile
    var phase = Phase.PEINTURE
        private set

    /** Selon la phase : cases à retoucher, ou numéro de la zone en cours de remplissage. */
    @Volatile
    var detail = 0
        private set

    /** Couleur en cours, et nombre de couleurs à peindre. */
    @Volatile
    var rang = 0
        private set

    @Volatile
    var couleurs = 0
        private set

    var retouchees = 0
        private set
    var zonesRemplies = 0
        private set
    var fuites = 0
        private set

    private val utilisees = cases.filter { it >= 0 }.map { it.toInt() }.distinct().toIntArray()
    private val illisibles = HashSet<Int>()
    private var pageConnue = -1

    /** Vrai une fois la toile entière couverte par un coup de pot : plus aucune case ne montre les rayures de la toile vide. */
    private var fondVerse = false

    init {
        couleurs = utilisees.size
    }

    /**
     * Peint le dessin. [faites] : les cases déjà peintes d'un dessin interrompu (aucune pour un dessin neuf).
     * Rend le nombre de cases qui manquent encore à la fin, d'après la dernière relecture.
     */
    fun peindre(faites: BooleanArray): Int {
        val presence = IntArray(Nuancier.TAILLE)
        for (c in cases) if (c >= 0) presence[c.toInt()]++
        // Les couleurs dans l'ordre des pages de nuances (moins de flèches à toucher), la plus présente d'abord dans une page.
        val ordre = utilisees.sortedWith(compareBy<Int> { Nuancier.PAGE[it] }.thenByDescending { presence[it] })
        val outils = r.outils

        var reprise = faites.any { it }
        if (reprise && voir) {
            // La toile a-t-elle été vidée depuis l'arrêt ? On le voit sur les cases vérifiables déjà peintes.
            val lue = lireToile()
            if (lue != null) {
                var vues = 0
                var enPlace = 0
                for (n in cases.indices) {
                    val k = cases[n].toInt()
                    if (faites[n] && k >= 0 && Nuancier.verifiable(k) && lue[n] >= 0) {
                        vues++
                        if (enPlace(lue[n], k)) enPlace++
                    }
                }
                if (vues >= 10 && enPlace * 10 < vues) {
                    atelier.journal("la toile ne montre plus les cases peintes avant l'arrêt, dessin repris du début")
                    java.util.Arrays.fill(faites, false)
                    atelier.toutOublier()
                    reprise = false
                }
            }
        }
        atelier.journal(
            "${largeur}×$hauteur · ${utilisees.size} couleurs (${if (avecNuances) "nuances" else "16 couleurs"}) · " +
                "${cases.count { it >= 0 }} cases" + (if (reprise) " · reprise à ${faites.count { it }} cases" else "") +
                (if (avecPot) " · pot de peinture" else "")
        )

        // Avec les 16 couleurs, la palette principale doit être à l'écran : si le jeu montre une page de nuances, on en sort.
        val nuances = r.nuances
        if (!avecNuances && nuances != null && voir && lirePage(journal = false) >= 0) {
            atelier.tracer(listOf(appui(nuances[RETOUR], PAUSE_OUTIL_MS)))
        }

        // Le pot ne sert que sur un dessin neuf, avec les outils repérés et un écran qu'on peut relire : une fuite
        // qu'on ne verrait pas ruinerait le dessin. En reprise, tout se fait au crayon.
        if (avecPot && outils != null && voir && !reprise) {
            peindreAuPot(ordre, presence, outils)
        } else {
            if (avecPot) atelier.journal("pot de peinture écarté (reprise, outils non repérés ou écran illisible)")
            if (outils != null) atelier.tracer(listOf(appui(outils[CRAYON], PAUSE_OUTIL_MS)))
            var i = 0
            for (k in ordre) {
                rang = ++i
                val masque = BooleanArray(cases.size) { cases[it].toInt() == k && !faites[it] }
                if (masque.none { it }) continue
                phase = Phase.PEINTURE
                choisir(k)
                crayon(masque)
                verifier(k, BooleanArray(cases.size) { cases[it].toInt() == k })
            }
        }

        // Vérification finale de toutes les couleurs : une case a pu être recouverte par un trait voisin.
        var manquantes = 0
        if (voir) {
            phase = Phase.VERIFICATION
            atelier.attendre(DELAI_CAPTURE_MS)
            val premiere = lireToile()
            if (premiere != null) {
                var repeint = false
                for (k in ordre) {
                    if (!relisible(k) || k in illisibles) continue
                    val masque = BooleanArray(cases.size) { cases[it].toInt() == k && !enPlace(premiere[it], k) }
                    val combien = masque.count { it }
                    if (combien == 0) continue
                    atelier.journal("vérification finale · couleur $k · $combien cases à repeindre")
                    phase = Phase.RETOUCHES
                    detail = combien
                    retouchees += combien
                    repeint = true
                    choisir(k)
                    crayon(masque)
                }
                var derniere: IntArray = premiere
                if (repeint) {
                    phase = Phase.VERIFICATION
                    atelier.attendre(DELAI_CAPTURE_MS)
                    derniere = lireToile() ?: premiere
                }
                for (n in cases.indices) {
                    val k = cases[n].toInt()
                    if (k >= 0 && relisible(k) && k !in illisibles && !enPlace(derniere[n], k)) manquantes++
                }
            }
        }
        // On rend au joueur la palette qu'il connaît.
        if (avecNuances && nuances != null && pageConnue >= 0) atelier.tracer(listOf(appui(nuances[RETOUR], PAUSE_OUTIL_MS)))
        atelier.journal("terminé · $retouchees cases retouchées · $manquantes manquantes · $zonesRemplies zones au pot · $fuites fuites")
        return manquantes
    }

    /**
     * Mode contours (`_paint_outline` de draw.py) : le fond d'un coup de pot si la toile entière est à peindre, les
     * contours de chaque couleur au crayon (vérifiés : un contour troué ferait fuir le pot), puis un coup de pot
     * par zone, relu à chaque fois. Une fuite est annulée et la zone repeinte au crayon.
     */
    private fun peindreAuPot(ordre: List<Int>, presence: IntArray, outils: List<PointEcran>) {
        // Le fond : la couleur la plus présente, si aucune case ne doit rester vide et si on sait la relire.
        var fond = -1
        val dominante = ordre.maxByOrNull { presence[it] }!!
        if (cases.none { it < 0 } && Nuancier.verifiable(dominante)) {
            phase = Phase.REMPLISSAGE
            detail = 0
            choisir(dominante)
            atelier.tracer(listOf(appui(outils[POT], PAUSE_OUTIL_MS), appui(centre(largeur / 2, hauteur / 2), PAUSE_POT_MS)))
            atelier.attendre(DELAI_CAPTURE_MS)
            val lue = lireToile()
            val attendues = presence[dominante]
            val enPlace = if (lue == null) attendues else cases.indices.count { cases[it].toInt() == dominante && enPlace(lue[it], dominante) }
            if (enPlace * 10 >= attendues * 8) {
                fond = dominante
                fondVerse = true
                atelier.marquer(cases.indices.filter { cases[it].toInt() == dominante }.toIntArray())
                zonesRemplies++
            } else {
                atelier.journal("le pot n'a pas rempli la toile ($enPlace cases sur $attendues), fond peint au crayon")
            }
        }
        atelier.tracer(listOf(appui(outils[CRAYON], PAUSE_OUTIL_MS)))

        val plan = PlanDessin.contours(cases, largeur, hauteur, fond, POT_MINIMUM)
        val secours = LinkedHashMap<Int, BooleanArray>()
        // A. Les contours, couleur par couleur. Une couleur qu'on ne sait pas relire est peinte en entier au crayon.
        var i = 0
        val aPeindre = ordre.filter { it != fond }
        couleurs = aPeindre.size
        for (k in aPeindre) {
            rang = ++i
            val masque = plan.crayon[k] ?: BooleanArray(cases.size)
            if (!relisible(k)) plan.zones[k]?.forEach { z -> for (c in z.cases) masque[c] = true }
            if (masque.none { it }) continue
            phase = Phase.PEINTURE
            choisir(k)
            crayon(masque)
            verifier(k, masque)
        }
        // B. Le pot, zone par zone.
        val aRemplir = aPeindre.filter { relisible(it) && !plan.zones[it].isNullOrEmpty() }
        if (aRemplir.isNotEmpty()) {
            atelier.attendre(DELAI_CAPTURE_MS)
            var avant = lireToile()
            var numero = 0
            for (k in aRemplir) {
                choisir(k)
                atelier.tracer(listOf(appui(outils[POT], PAUSE_OUTIL_MS)))
                for (z in plan.zones[k]!!) {
                    phase = Phase.REMPLISSAGE
                    detail = ++numero
                    var remplie = false
                    for (essai in 0..1) {
                        // Second essai décalé d'un tiers de case : le premier est peut-être tombé sur une frontière.
                        val decalage = if (essai == 0) 0f else 0.3f
                        atelier.tracer(listOf(appui(centre(z.graine % largeur, z.graine / largeur, decalage), PAUSE_POT_MS)))
                        atelier.attendre(DELAI_CAPTURE_MS)
                        val apres = lireToile()
                        val reference = avant
                        if (apres == null || reference == null) {
                            // Écran illisible : on ne peut pas savoir, la vérification finale rattrapera au crayon.
                            remplie = true
                            avant = apres
                            break
                        }
                        val debord = cases.indices.count { cases[it].toInt() != k && proche(apres[it], k) && !proche(reference[it], k) }
                        if (debord > 0) {
                            fuites++
                            atelier.journal("fuite du pot (couleur $k, zone de ${z.cases.size} cases, $debord cases débordées), annulée")
                            atelier.tracer(listOf(appui(outils[ANNULER], PAUSE_POT_MS)))
                            break
                        }
                        if (proche(apres[z.graine], k) || apres[z.graine] < 0) {
                            remplie = true
                            avant = apres
                            break
                        }
                    }
                    if (remplie) {
                        zonesRemplies++
                        atelier.marquer(z.cases)
                    } else {
                        val masque = secours.getOrPut(k) { BooleanArray(cases.size) }
                        for (c in z.cases) masque[c] = true
                    }
                }
            }
        }
        // C. Crayon de secours pour les zones que le pot n'a pas remplies.
        atelier.tracer(listOf(appui(outils[CRAYON], PAUSE_OUTIL_MS)))
        for ((k, masque) in secours) {
            phase = Phase.PEINTURE
            choisir(k)
            crayon(masque)
            verifier(k, masque)
        }
    }

    /** Trace au crayon les cases de [masque], dans la couleur déjà choisie. */
    private fun crayon(masque: BooleanArray) {
        val segments = PlanDessin.segments(masque, largeur, hauteur)
        val gestes = ArrayList<Geste>(segments.size)
        val peintes = ArrayList<IntArray?>(segments.size)
        for (s in segments) {
            val a = centre(s.x0, s.y0)
            val b = centre(s.x1, s.y1)
            // Le jeu ne peint que les cases où il voit passer le doigt : la durée suit la longueur du trait.
            gestes.add(Geste(a.x, a.y, b.x, b.y, APPUI_CASE_MS + s.longueur.toLong() * caseMs))
            peintes.add(s.cases(largeur))
        }
        atelier.tracer(gestes, peintes)
    }

    /**
     * Relit la toile et repeint les cases de [masque] qui ne montrent pas la couleur [k], deux fois au plus.
     * Une couleur dont plus de la moitié des cases « manquent » encore après une retouche est jugée illisible
     * et laissée de côté, plutôt que repeinte sans fin.
     */
    private fun verifier(k: Int, masque: BooleanArray) {
        if (!voir || !relisible(k)) return
        val attendues = masque.count { it }
        for (passe in 1..PASSES_RETOUCHE) {
            phase = Phase.VERIFICATION
            atelier.attendre(DELAI_CAPTURE_MS)
            val lue = lireToile() ?: return
            val manque = BooleanArray(cases.size) { masque[it] && !enPlace(lue[it], k) }
            val combien = manque.count { it }
            atelier.journal("couleur $k · relecture $passe · $combien cases manquantes sur $attendues")
            if (combien == 0) return
            if (passe > 1 && combien * 2 > attendues && combien > 20) {
                illisibles.add(k)
                return
            }
            phase = Phase.RETOUCHES
            detail = combien
            retouchees += combien
            crayon(manque)
        }
    }

    // ------------------------------------------------------------------ choisir une couleur

    /** Choisit la nuance [k] dans le jeu (`Drawer._select` de draw.py). */
    private fun choisir(k: Int) {
        if (!avecNuances) {
            atelier.tracer(listOf(appui(pastille(Nuancier.PRINCIPALE[k]), PAUSE_PASTILLE_MS)))
            return
        }
        val n = r.nuances ?: throw NuancesIllisibles()
        val cible = Nuancier.PAGE[k]
        var page = if (pageConnue >= 0) pageConnue else lirePage(journal = false)
        if (page < 0) {
            // Les nuances ne sont pas affichées : le bouton « palette » les ouvre.
            atelier.tracer(listOf(appui(n[BOUTON], PAUSE_PAGE_MS)))
            page = lirePage(journal = false)
        }
        if (page < 0) {
            // Le bouton n'a rien ouvert : on choisit la famille dans la palette principale, puis on réessaie.
            atelier.tracer(listOf(appui(pastille(Nuancier.FAMILLES[cible]), PAUSE_PASTILLE_MS), appui(n[BOUTON], PAUSE_PAGE_MS)))
            page = lirePage(journal = true)
        }
        if (page < 0) throw NuancesIllisibles()
        var essais = 0
        while (page != cible) {
            if (essais++ >= ESSAIS_PAGE) throw NuancesIllisibles()
            val fleche = if (cible > page) n[SUIVANT] else n[PRECEDENT]
            atelier.tracer(List(abs(cible - page)) { appui(fleche, PAUSE_PAGE_MS) })
            page = lirePage(journal = true)
            if (page < 0) throw NuancesIllisibles()
            if (page != cible) atelier.journal("page de nuances ${page + 1} au lieu de ${cible + 1}, nouvel essai")
        }
        pageConnue = page
        atelier.tracer(listOf(appui(nuance(n, Nuancier.RANG[k]), PAUSE_PASTILLE_MS)))
    }

    /**
     * La page de nuances que le jeu affiche (0 = noir … 12 = rose), ou -1 si les nuances ne sont pas ouvertes.
     * PC lit la pastille encadrée de la bande des familles ; ici on compare les dix emplacements de nuances aux
     * couleurs attendues de chaque famille, ce qui se passe d'un repère de plus.
     */
    private fun lirePage(journal: Boolean): Int {
        val n = r.nuances ?: return -1
        val image = atelier.capturer() ?: return -1
        val lues = IntArray(Nuancier.COLONNES * Nuancier.LIGNES) { moyenne(image, nuance(n, it)) }
        image.fermer()
        var meilleure = -1
        var bonnes = 0f
        var ecarts = Long.MAX_VALUE
        for (page in Nuancier.FAMILLES.indices) {
            val taille = Nuancier.taille(page)
            var b = 0
            var e = 0L
            for (rang in 0 until taille) {
                val d = if (lues[rang] < 0) Int.MAX_VALUE / 16 else Nuancier.ecartBrut(lues[rang], Nuancier.COULEURS[Nuancier.nuance(page, rang)])
                if (d <= TOLERANCE) b++
                e += d
            }
            val part = b.toFloat() / taille
            if (part > bonnes || (part == bonnes && e < ecarts)) {
                bonnes = part
                ecarts = e
                meilleure = page
            }
        }
        if (bonnes >= PART_NUANCES) return meilleure
        if (journal) atelier.journal("page de nuances illisible · " + lues.joinToString(" ") { if (it < 0) "caché" else String.format("%06X", it) })
        return -1
    }

    // ------------------------------------------------------------------ regarder l'écran

    /** Couleur moyenne (0xRRGGBB) de cinq pixels autour d'un point, ou -1 si l'un d'eux est caché. */
    private fun moyenne(image: Capture, p: PointEcran): Int {
        var rouge = 0
        var vert = 0
        var bleu = 0
        for (d in 0 until 5) {
            val c = image.couleur(p.x.toInt() + CROIX_X[d], p.y.toInt() + CROIX_Y[d])
            if (c < 0) return -1
            rouge += (c shr 16) and 0xFF
            vert += (c shr 8) and 0xFF
            bleu += c and 0xFF
        }
        return ((rouge / 5) shl 16) or ((vert / 5) shl 8) or (bleu / 5)
    }

    /** La couleur (0xRRGGBB) du centre de chaque case de la toile, ou -1 pour une case cachée par une de nos fenêtres. */
    private fun lireToile(): IntArray? {
        val image = atelier.capturer() ?: return null
        val lue = IntArray(largeur * hauteur) {
            val c = centre(it % largeur, it / largeur)
            image.couleur(c.x.toInt(), c.y.toInt())
        }
        image.fermer()
        return lue
    }

    /**
     * Peut-on vérifier à l'écran qu'une case est de la nuance [k] ? Pas le blanc ni le crème sur la toile vide, trop
     * proches de ses rayures ; toutes les couleurs une fois le fond versé au pot.
     */
    private fun relisible(k: Int): Boolean = fondVerse || Nuancier.verifiable(k)

    /** La couleur lue est-elle bien la nuance [k], à peu de chose près ? */
    private fun proche(lue: Int, k: Int): Boolean = lue >= 0 && Nuancier.ecartBrut(lue, Nuancier.COULEURS[k]) <= TOLERANCE

    /**
     * La case montre-t-elle la nuance [k] ? Oui si sa couleur en est proche, ou si, parmi les couleurs du dessin
     * et les deux tons de la toile vide, c'est [k] qui lui ressemble le plus (la couleur déposée par le jeu n'a
     * pas été relevée sur mobile : elle peut différer un peu de celle de la pastille). Une case cachée compte pour bonne.
     */
    private fun enPlace(lue: Int, k: Int): Boolean {
        if (lue < 0) return true
        val d = Nuancier.ecartBrut(lue, Nuancier.COULEURS[k])
        if (d <= TOLERANCE) return true
        for (vide in Nuancier.TOILE_VIDE) if (Nuancier.ecartBrut(lue, vide) <= d) return false
        for (autre in utilisees) if (autre != k && Nuancier.ecartBrut(lue, Nuancier.COULEURS[autre]) < d) return false
        return true
    }

    // ------------------------------------------------------------------ où appuyer

    /** Centre de la case (x, y) de la toile, décalé de [decalage] case vers le bas et la droite. */
    private fun centre(x: Int, y: Int, decalage: Float = 0f) = PointEcran(
        r.toile0.x + (x + 0.5f + decalage) * (r.toile1.x - r.toile0.x) / largeur,
        r.toile0.y + (y + 0.5f + decalage) * (r.toile1.y - r.toile0.y) / hauteur,
    )

    /** Centre de la pastille [k] de la palette principale : 2 colonnes × 8 lignes entre la première et la dernière. */
    private fun pastille(k: Int) = PointEcran(
        r.palette0.x + (r.palette1.x - r.palette0.x) * (k % 2),
        r.palette0.y + (r.palette1.y - r.palette0.y) * (k / 2) / 7,
    )

    /** Centre de la nuance de rang [rang] : 2 colonnes × 5 lignes entre la première et la dixième. */
    private fun nuance(n: List<PointEcran>, rang: Int) = PointEcran(
        n[PREMIERE].x + (n[DERNIERE].x - n[PREMIERE].x) * (rang % Nuancier.COLONNES) / (Nuancier.COLONNES - 1),
        n[PREMIERE].y + (n[DERNIERE].y - n[PREMIERE].y) * (rang / Nuancier.COLONNES) / (Nuancier.LIGNES - 1),
    )

    private fun appui(p: PointEcran, pauseMs: Long) = Geste(p.x, p.y, p.x, p.y, APPUI_PASTILLE_MS, pauseMs)

    companion object {
        /** Places des repères dans [Reperes.nuances] et [Reperes.outils]. */
        const val BOUTON = 0
        const val RETOUR = 1
        const val PRECEDENT = 2
        const val SUIVANT = 3
        const val PREMIERE = 4
        const val DERNIERE = 5
        const val CRAYON = 0
        const val POT = 1
        const val ANNULER = 2

        /**
         * Appui de base d'un trait ; s'y ajoute le temps par case traversée (réglable). Relevé dans le jeu : il faut
         * aussi ~90 ms doigt levé entre deux traits (voir [Traceur]).
         */
        private const val APPUI_CASE_MS = 90L

        /** Un appui plus long sur les pastilles et les boutons. */
        private const val APPUI_PASTILLE_MS = 120L

        /** Après un changement de couleur : une pastille ratée peindrait toute la couleur suivante avec la précédente. */
        private const val PAUSE_PASTILLE_MS = 160L
        private const val PAUSE_OUTIL_MS = 250L
        private const val PAUSE_PAGE_MS = 220L
        private const val PAUSE_POT_MS = 400L

        /** Le temps que le dernier trait s'affiche avant de regarder l'écran. */
        private const val DELAI_CAPTURE_MS = 600L
        private const val PASSES_RETOUCHE = 2
        private const val ESSAIS_PAGE = 3

        /** Une page de nuances est reconnue si six emplacements sur dix montrent la couleur attendue. */
        private const val PART_NUANCES = 0.6f

        /** Carré de l'écart RGB toléré entre une couleur lue et celle qu'on attend. */
        private const val TOLERANCE = 34 * 34

        /** En dessous de 40 cases, une zone est peinte au crayon : un coup de pot et sa relecture coûtent plus cher. */
        private const val POT_MINIMUM = 40

        private val CROIX_X = intArrayOf(0, -2, 2, 0, 0)
        private val CROIX_Y = intArrayOf(0, 0, 0, -2, 2)
    }
}
