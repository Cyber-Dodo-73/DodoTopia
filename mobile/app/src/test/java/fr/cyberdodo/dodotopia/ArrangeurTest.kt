package fr.cyberdodo.dodotopia

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Transposition, tonalité commune, couverture, et l'arrangeur comparé à arrange.py du client PC. */
class ArrangeurTest {

    private val luth = Dispositions.parId("15-3")       // do4 à do6, sans dièses
    private val piano22 = Dispositions.parId("22")      // do3 à do6, sans dièses
    private val piano37 = Dispositions.parId("37")      // do3 à do6, toutes les touches

    private fun gamme(depuis: Int, intervalles: List<Int> = listOf(0, 2, 4, 5, 7, 9, 11, 12)) =
        intervalles.mapIndexed { i, ecart -> NoteMidi(i * 500L, 400, depuis + ecart) }

    /** La hauteur que joue chaque touche d'une frappe. */
    private fun hauteurs(a: Arrangement, d: Disposition) = a.frappes.map { f -> f.touches.map { d.notes[it] } }

    @Test
    fun doMajeurSansTransposition() {
        val a = Arrangeur.arranger(gamme(60), luth, melodie = false)
        assertEquals(0, a.decalage)
        assertEquals(100, a.couverture)
        assertEquals(listOf(60, 62, 64, 65, 67, 69, 71, 72), hauteurs(a, luth).map { it.single() })
        assertEquals(3900L, a.dureeMs)
        assertFalse(a.melodie)
    }

    @Test
    fun transpositionVersLaGammeDuClavier() {
        // Ré majeur, une octave trop bas : le clavier sans dièses demande deux demi-tons de moins et une octave de plus.
        val a = Arrangeur.arranger(gamme(50), luth, melodie = false)
        assertEquals(10, a.decalage)
        assertEquals(100, a.couverture)
        assertEquals(listOf(60, 62, 64, 65, 67, 69, 71, 72), hauteurs(a, luth).map { it.single() })
    }

    @Test
    fun clavierChromatiqueNeChangeQueLOctave() {
        val a = Arrangeur.arranger(gamme(26), piano37, melodie = false)
        assertEquals(0, Math.floorMod(a.decalage, 12))
        assertEquals(100, a.couverture)
        // L'arrangeur ne passe jamais sur un clavier qui a toutes les touches, même demandé.
        val b = Arrangeur.arranger(gamme(26), piano37, melodie = true)
        assertFalse(b.melodie)
        assertEquals(a.decalage, b.decalage)
    }

    @Test
    fun tonaliteImposeeEtOctave() {
        // Salon : la tonalité vient du chef, seule l'octave reste libre.
        val notes = gamme(62)
        val a = Arrangeur.arranger(notes, luth, tonalite = -2, melodie = false)
        assertEquals(-2, a.decalage)
        assertEquals(100, a.couverture)
        val impose = Arrangeur.arranger(notes, luth, tonalite = 3, melodie = false)
        assertEquals(3, Math.floorMod(impose.decalage, 12))
        // Partie d'orchestre : une octave de plus que le choix automatique.
        val plusHaut = Arrangeur.arranger(notes, luth, tonalite = -2, octave = 1, melodie = false)
        assertEquals(a.decalage + 12, plusHaut.decalage)
    }

    @Test
    fun tonaliteCommune() {
        assertEquals(0, Arrangeur.tonaliteCommune(emptyList()))
        assertEquals(0, Arrangeur.tonaliteCommune(gamme(60)))
        assertEquals(0, Arrangeur.tonaliteCommune(gamme(36)))        // l'octave ne compte pas
        assertEquals(-2, Arrangeur.tonaliteCommune(gamme(62)))       // ré majeur
        assertEquals(-5, Arrangeur.tonaliteCommune(gamme(65)))       // fa majeur : -5 plutôt que +7, hors plage
        assertEquals(5, Arrangeur.tonaliteCommune(gamme(67)))        // sol majeur
        // Le décalage rendu met bien toutes les notes sur la gamme de do majeur.
        for (tonique in 60..71) {
            val e = Arrangeur.tonaliteCommune(gamme(tonique))
            assertTrue(e in -6..5)
            assertTrue(gamme(tonique).all { Math.floorMod(it.hauteur + e, 12) in setOf(0, 2, 4, 5, 7, 9, 11) })
        }
    }

    @Test
    fun couvertureEtNotesRapprochees() {
        // Do, do dièse, ré, ré dièse : deux notes sur quatre n'ont pas de touche sur un clavier sans dièses.
        val notes = listOf(60, 61, 62, 63).mapIndexed { i, h -> NoteMidi(i * 500L, 400, h) }
        val a = Arrangeur.arranger(notes, luth, tonalite = 0, melodie = false)
        assertEquals(50, a.couverture)
        // Une altération absente va à la touche voisine, la plus grave en cas d'égalité.
        assertEquals(listOf(60, 60, 62, 62), hauteurs(a, luth).map { it.single() })
        // Sur le piano complet, tout est exact.
        assertEquals(100, Arrangeur.arranger(notes, piano37, melodie = false).couverture)
    }

    @Test
    fun replisDOctaveEtAccords() {
        // Hors registre : repliée d'une octave, donc jouée mais pas « exacte ».
        val notes = listOf(NoteMidi(0, 400, 60), NoteMidi(500, 400, 64), NoteMidi(1000, 400, 67), NoteMidi(1500, 400, 96))
        val a = Arrangeur.arranger(notes, luth, tonalite = 0, melodie = false)
        assertEquals(84, hauteurs(a, luth).last().single())
        assertEquals(75, a.couverture)

        // Un accord tient dans une frappe ; deux notes sur la même touche n'en font qu'une, avec la plus longue durée.
        val accord = listOf(NoteMidi(0, 300, 60), NoteMidi(5, 900, 61), NoteMidi(8, 200, 67), NoteMidi(400, 100, 72))
        val b = Arrangeur.arranger(accord, luth, tonalite = 0, melodie = false)
        assertEquals(2, b.frappes.size)
        assertEquals(listOf(60, 67), hauteurs(b, luth)[0])
        assertEquals(listOf(900, 200), b.frappes[0].durees!!.toList())
        assertTrue(b.frappes.all { it.durees!!.size == it.touches.size })

        // Sans arrangeur : six touches au plus, la basse et les plus aiguës.
        val grappe = (0 until 10).map { NoteMidi(0, 300, luth.notes[it]) }
        val c = Arrangeur.arranger(grappe, luth, tonalite = 0, melodie = false)
        assertEquals(listOf(0, 5, 6, 7, 8, 9), c.frappes.single().touches.toList())
    }

    @Test
    fun dureeImposeeEtMorceauVide() {
        val vide = Arrangeur.arranger(emptyList(), luth, dureeMs = 5000)
        assertTrue(vide.frappes.isEmpty())
        assertEquals(5000L, vide.dureeMs)
        // Partie d'orchestre : filtrer les pistes ne raccourcit pas le morceau.
        assertEquals(90_000L, Arrangeur.arranger(gamme(60), luth, dureeMs = 90_000).dureeMs)
    }

    @Test
    fun arrangeurGardeLaMelodieEtAllegeLAccompagnement() {
        // Mélodie do-ré-mi-fa au-dessus d'un accord dont une note (mi bémol) n'a pas de touche juste.
        val notes = ArrayList<NoteMidi>()
        for ((i, h) in listOf(72, 74, 76, 77).withIndex()) {
            notes.add(NoteMidi(i * 500L, 450, h))
            notes.add(NoteMidi(i * 500L, 450, 60))
            notes.add(NoteMidi(i * 500L, 450, 63))
        }
        val sans = Arrangeur.arranger(notes, luth, tonalite = 0, melodie = false)
        val avec = Arrangeur.arranger(notes, luth, tonalite = 0, melodie = true)
        assertTrue(avec.melodie)
        // Sans arrangeur, le mi bémol est joué à côté ; avec, il est omis et tout ce qui reste est juste.
        assertTrue(hauteurs(sans, luth).all { 62 in it })
        assertTrue(hauteurs(avec, luth).none { 62 in it })
        assertTrue(avec.frappes.all { it.touches.size == 2 })
        assertEquals(4, avec.omises)
        assertEquals(100, avec.couverture)
        assertEquals(listOf(72, 74, 76, 77), hauteurs(avec, luth).map { it.last() })
        assertTrue(hauteurs(avec, luth).all { it.first() == 60 })
    }

    @Test
    fun arrangeurRespecteLaPolyphonie() {
        val notes = ArrayList<NoteMidi>()
        for (i in 0 until 8) {
            for (h in listOf(48, 52, 55, 60, 64, 67, 72)) notes.add(NoteMidi(i * 400L, 300, h))
        }
        val a = Arrangeur.arranger(notes, piano22, tonalite = 0, melodie = true)
        assertTrue(a.frappes.all { it.touches.size <= 4 })
        // La mélodie (la voix du haut) est toujours là.
        assertTrue(hauteurs(a, piano22).all { it.last() == 72 })
        assertTrue(a.omises > 0)
    }

    /** Générateur partagé avec scratchpad/mus/reference.py : les mêmes notes des deux côtés. */
    private fun morceau(graine: Long, combien: Int = 200): List<NoteMidi> {
        var x = graine
        fun suivant(): Long {
            x = (x * 1103515245L + 12345L) % 2147483648L
            return x
        }
        val notes = ArrayList<NoteMidi>()
        var t = 0L
        repeat(combien) {
            t += 100 * (1 + suivant() % 4)
            val taille = (1 + suivant() % 4).toInt()
            val vues = HashSet<Int>()
            repeat(taille) {
                val h = (40 + suivant() % 50).toInt()
                val d = (80 + suivant() % 900).toInt()
                if (vues.add(h)) notes.add(NoteMidi(t, d, h))
            }
        }
        return notes
    }

    private fun empreinte(a: Arrangement): Long {
        var h = 7L
        for (f in a.frappes) {
            for (v in listOf(f.tMs) + f.touches.sorted().map { it.toLong() }) h = (h * 131 + v + 1) % 1_000_000_007L
        }
        return h
    }

    private fun commeLePc(d: Disposition, graine: Long, tonalite: Int?, octave: Int, decalage: Int, frappes: Int, couverture: Int, empreinte: Long) {
        val a = Arrangeur.arranger(morceau(graine), d, tonalite, octave, melodie = true)
        val cas = "${d.id} graine $graine tonalité $tonalite octave $octave"
        assertEquals(cas, decalage, a.decalage)
        assertEquals(cas, frappes, a.frappes.size)
        assertEquals(cas, couverture, a.couverture)
        assertEquals(cas, empreinte, empreinte(a))
    }

    /**
     * Les mêmes morceaux passés dans arrange.arrange puis fit_notes du client PC (reference.py) : même
     * transposition, mêmes frappes, mêmes touches. C'est ce qui fait jouer mobile et PC à l'unisson dans un salon.
     */
    @Test
    fun arrangeurIdentiqueAuPc() {
        commeLePc(luth, 1, null, 0, -5, 191, 89, 497900273)
        commeLePc(luth, 1, -2, 0, -2, 181, 79, 257984613)
        commeLePc(luth, 1, 3, 1, 3, 188, 87, 985819339)
        commeLePc(luth, 2, null, 0, -6, 181, 77, 980888940)
        commeLePc(luth, 2, -2, 0, -2, 183, 72, 980170868)
        commeLePc(luth, 2, 3, 1, 15, 170, 58, 160343171)
        commeLePc(luth, 3, null, 0, -5, 193, 87, 142712097)
        commeLePc(luth, 3, -2, 0, -2, 191, 77, 857981057)
        commeLePc(luth, 3, 3, 1, 3, 194, 85, 21507109)
        commeLePc(piano22, 1, null, 0, -5, 192, 90, 791079952)
        commeLePc(piano22, 1, -2, 0, -2, 183, 81, 926590528)
        commeLePc(piano22, 1, 3, 1, 3, 192, 89, 949038888)
        commeLePc(piano22, 2, null, 0, -6, 183, 78, 705563006)
        commeLePc(piano22, 2, -2, 0, -2, 185, 72, 10528226)
        commeLePc(piano22, 2, 3, 1, 3, 170, 58, 399676794)
        commeLePc(piano22, 3, null, 0, -5, 194, 89, 85943310)
        commeLePc(piano22, 3, -2, 0, -2, 194, 79, 999496967)
        commeLePc(piano22, 3, 3, 1, 3, 197, 88, 717134332)
    }

    @Test
    fun suiteDUnMorceauRejoint() {
        val a = Arrangeur.arranger(gamme(60), luth, tonalite = 0, melodie = false)
        assertTrue(a.depuis(0) === a)
        val suite = a.depuis(1200)
        // Les frappes déjà passées sont laissées, les autres repartent de zéro.
        assertEquals(listOf(300L, 800L, 1300L, 1800L, 2300L), suite.frappes.map { it.tMs })
        assertEquals(listOf(65, 67, 69, 71, 72), hauteurs(suite, luth).map { it.single() })
        assertEquals(a.dureeMs - 1200, suite.dureeMs)
        assertEquals(a.decalage, suite.decalage)
        assertTrue(a.depuis(10_000).frappes.isEmpty())
        assertEquals(0L, a.depuis(10_000).dureeMs)
    }
}
