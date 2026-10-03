package fr.cyberdodo.dodotopia

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Le découpage en gestes de la lecture. Les règles viennent de dispatchGesture : un seul geste à la fois
 * (le suivant annule celui qui court), 20 traits au plus par geste.
 */
class GestesTest {

    private fun frappe(tMs: Long, vararg touches: Int, duree: Int = 300) =
        Frappe(tMs, touches, IntArray(touches.size) { duree })

    private fun finDe(geste: List<Trait>) = geste.maxOf { it.debut + it.duree }

    /** Ce que le jeu exige de tout découpage, quel que soit le mode. */
    private fun verifier(gestes: List<List<Trait>>, maxTraits: Int = Gestes.MAX_TRAITS) {
        assertTrue(gestes.all { it.isNotEmpty() && it.size <= maxTraits })
        val tous = gestes.flatten()
        assertTrue(tous.zipWithNext().all { (a, b) -> a.debut <= b.debut })
        assertTrue(tous.all { it.duree >= 1 })
        // Deux appuis ne se mêlent jamais sur une même touche.
        for ((_, memes) in tous.groupBy { it.touche }) {
            assertTrue(memes.zipWithNext().all { (a, b) -> a.debut + a.duree <= b.debut })
        }
    }

    /** Aucun geste n'est envoyé avant la fin du précédent, marge comprise. */
    private fun sansChevauchement(gestes: List<List<Trait>>) {
        for ((a, b) in gestes.zipWithNext()) {
            assertTrue("geste fini à ${finDe(a)}, suivant à ${b[0].debut}", finDe(a) + Gestes.MARGE_MS <= b[0].debut)
        }
    }

    @Test
    fun appuisCourtsParDefaut() {
        val frappes = listOf(frappe(0, 0), frappe(500, 1, 2, 3), frappe(1000, 4, duree = 2000))
        val traits = Gestes.traits(frappes, 15, 1f, 0, 40)
        assertEquals(listOf(0L, 500L, 500L, 500L, 1000L), traits.map { it.debut })
        // Sans le mode « notes tenues », la durée des notes est ignorée.
        assertTrue(traits.all { it.duree == 40L })
        val gestes = Gestes.decouper(traits)
        // Un accord part dans un seul geste ; des notes espacées, dans des gestes séparés.
        assertEquals(listOf(1, 3, 1), gestes.map { it.size })
        verifier(gestes)
        sansChevauchement(gestes)
    }

    @Test
    fun vitesseEtReprise() {
        val frappes = listOf(frappe(0, 0), frappe(1000, 1), frappe(2000, 2), frappe(3000, 3))
        // À 200 %, les écarts sont divisés par deux ; la reprise à 1 s laisse la première frappe.
        val traits = Gestes.traits(frappes, 15, 2f, 1000, 40)
        assertEquals(listOf(1, 2, 3), traits.map { it.touche })
        assertEquals(listOf(0L, 500L, 1000L), traits.map { it.debut })
        // Une touche hors du clavier calibré est ignorée au lieu de faire planter la lecture.
        assertEquals(1, Gestes.traits(listOf(frappe(0, 2, 40, -1)), 15, 1f, 0, 40).size)
    }

    @Test
    fun memeToucheRepetee() {
        // Rejouée 60 ms plus tard : le premier appui est raccourci pour laisser le doigt se lever.
        val traits = Gestes.traits(listOf(frappe(0, 5), frappe(60, 5)), 15, 1f, 0, 80)
        assertEquals(2, traits.size)
        assertEquals(60 - Gestes.RELACHE_MS, traits[0].duree)
        // Trop près pour que le jeu voie deux appuis : le second est laissé.
        assertEquals(1, Gestes.traits(listOf(frappe(0, 5), frappe(20, 5)), 15, 1f, 0, 80).size)
    }

    @Test
    fun appuisQuiSeChevauchentDansUnMemeGeste() {
        // 30 ms d'écart pour 40 ms d'appui : envoyés séparément, chaque geste annulerait le précédent.
        val frappes = (0 until 8).map { frappe(it * 30L, it) }
        val gestes = Gestes.decouper(Gestes.traits(frappes, 15, 1f, 0, 40))
        assertEquals(1, gestes.size)
        assertEquals(8, gestes[0].size)
        verifier(gestes)
    }

    @Test
    fun jamaisPlusDeVingtTraits() {
        // 60 notes serrées sur 15 touches : il faut couper, et finir chaque geste avant le suivant.
        val frappes = (0 until 60).map { frappe(it * 25L, it % 15) }
        val traits = Gestes.traits(frappes, 15, 1f, 0, 40)
        val gestes = Gestes.decouper(traits)
        assertEquals(60, gestes.sumOf { it.size })
        assertTrue(gestes.size >= 3)
        verifier(gestes)
        sansChevauchement(gestes)
    }

    @Test
    fun accordJamaisPartageEntreDeuxGestes() {
        // 18 notes seules puis un accord de 4 : le geste est coupé avant l'accord, pas au milieu.
        val frappes = (0 until 18).map { frappe(it * 30L, it % 9) } + frappe(540, 10, 11, 12, 13)
        val gestes = Gestes.decouper(Gestes.traits(frappes, 15, 1f, 0, 40))
        verifier(gestes)
        val accord = gestes.filter { g -> g.any { it.debut == 540L } }
        assertEquals(1, accord.size)
        assertEquals(4, accord[0].count { it.debut == 540L })
    }

    @Test
    fun gesteLongCoupePourResterInterruptible() {
        // Appuis courts enchaînés pendant 3 s : aucun geste ne dépasse la portée, pour que la pause réponde.
        val frappes = (0 until 100).map { frappe(it * 30L, it % 15) }
        val gestes = Gestes.decouper(Gestes.traits(frappes, 15, 1f, 0, 40))
        verifier(gestes)
        sansChevauchement(gestes)
        assertTrue(gestes.all { finDe(it) - it[0].debut <= Gestes.PORTEE_MAX_MS + 100 })
    }

    @Test
    fun notesTenues() {
        val frappes = listOf(frappe(0, 0, duree = 1000), frappe(2000, 1, duree = 10), frappe(3000, 2, duree = 9000))
        val traits = Gestes.traits(frappes, 15, 1f, 0, 40, tenue = true)
        // La durée de la note, jamais moins que l'appui court, jamais plus que le plafond.
        assertEquals(listOf(1000L, 40L, Gestes.TENUE_MAX_MS), traits.map { it.duree })
        // La vitesse raccourcit les tenues comme le reste.
        assertEquals(500L, Gestes.traits(frappes, 15, 2f, 0, 40, tenue = true)[0].duree)
        // Une frappe sans durées (test des touches) reste un appui court.
        assertEquals(40L, Gestes.traits(listOf(Frappe(0, intArrayOf(3))), 15, 1f, 0, 40, tenue = true)[0].duree)
        val gestes = Gestes.decouper(traits, tenue = true, appuiMs = 40)
        assertEquals(3, gestes.size)
        verifier(gestes)
        sansChevauchement(gestes)
    }

    @Test
    fun noteTenueRelacheeAvantDEtreRejouee() {
        val frappes = listOf(frappe(0, 4, duree = 800), frappe(500, 4, duree = 800))
        val traits = Gestes.traits(frappes, 15, 1f, 0, 40, tenue = true)
        assertEquals(500 - Gestes.RELACHE_MS, traits[0].duree)
        assertEquals(800L, traits[1].duree)
        // Les deux appuis se touchent presque : un seul geste, comme un accord étalé.
        assertEquals(1, Gestes.decouper(traits, tenue = true, appuiMs = 40).size)
    }

    @Test
    fun accordTenuDansUnSeulGeste() {
        // Une basse tenue 1,2 s sous quatre notes de mélodie : tout tient dans le geste de la basse.
        val frappes = listOf(frappe(0, 0, duree = 1200), frappe(0, 7, duree = 250), frappe(300, 8, duree = 250), frappe(600, 9, duree = 250), frappe(900, 10, duree = 250))
        val traits = Gestes.traits(frappes, 15, 1f, 0, 40, tenue = true)
        val gestes = Gestes.decouper(traits, tenue = true, appuiMs = 40)
        assertEquals(1, gestes.size)
        assertEquals(1200L, gestes[0][0].duree)
        verifier(gestes)
    }

    @Test
    fun tenuesLegatoCoupeesProprement() {
        // Une mélodie liée de 20 s, chaque note tenue jusqu'à la suivante et au-delà : tout se chevauche.
        val frappes = (0 until 80).map { frappe(it * 250L, it % 15, duree = 600) }
        val traits = Gestes.traits(frappes, 15, 1f, 0, 40, tenue = true)
        val gestes = Gestes.decouper(traits, tenue = true, appuiMs = 40)
        assertEquals(80, gestes.sumOf { it.size })
        verifier(gestes)
        sansChevauchement(gestes)
        // Plusieurs gestes (sinon la pause attendrait la fin du morceau), aucun démesuré.
        assertTrue(gestes.size >= 8)
        assertTrue(gestes.all { finDe(it) - it[0].debut <= 2 * Gestes.PORTEE_TENUE_MS + Gestes.TENUE_MAX_MS })
        // Une note coupée par la fin de son geste garde au moins la durée d'un appui court.
        assertTrue(traits.all { it.duree >= 40 })
        // Et les notes qui ne sont pas en bout de geste gardent leur durée entière.
        assertTrue(traits.count { it.duree == 600L } > traits.size / 2)
    }

    @Test
    fun tenuesDUnVraiArrangement() {
        // Un morceau arrangé passe de bout en bout, dans les deux modes, sans perdre une frappe.
        val notes = ArrayList<NoteMidi>()
        var x = 12345L
        var t = 0L
        repeat(400) {
            x = (x * 1103515245L + 12345L) % 2147483648L
            t += 60 + x % 300
            notes.add(NoteMidi(t, (100 + x % 1500).toInt(), (48 + x % 36).toInt()))
            if (x % 3 == 0L) notes.add(NoteMidi(t, 900, (48 + (x / 7) % 24).toInt()))
        }
        val d = Dispositions.parId("15-3")
        val a = Arrangeur.arranger(notes, d, melodie = true)
        for (tenue in listOf(false, true)) {
            val traits = Gestes.traits(a.frappes, d.notes.size, 1f, 0, 40, tenue)
            val gestes = Gestes.decouper(traits, tenue, 40)
            assertEquals(traits.size, gestes.sumOf { it.size })
            verifier(gestes)
            // Un accord n'est jamais partagé : tous les traits d'un même instant sont dans le même geste.
            val gesteDe = HashMap<Long, Int>()
            for ((g, geste) in gestes.withIndex()) {
                for (trait in geste) assertEquals(g, gesteDe.getOrPut(trait.debut) { g })
            }
        }
    }
}
