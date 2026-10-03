package fr.cyberdodo.dodotopia

import kotlin.math.max
import kotlin.math.min

/** Un appui sur une touche : début et durée en millisecondes réelles depuis le départ de la lecture. */
class Trait(val debut: Long, var duree: Long, val touche: Int)

/**
 * Le découpage d'un morceau arrangé en gestes : la partie de [Lecteur] qui ne dépend pas d'Android.
 *
 * dispatchGesture ne tient qu'un geste à la fois et 20 traits au plus par geste : les appuis qui se
 * chevauchent partent dans un même geste, et un geste doit être fini avant que le suivant soit envoyé.
 * Une note tenue ne peut donc pas enjamber deux gestes : elle est relâchée juste avant le geste suivant.
 */
object Gestes {
    /** Écart minimal entre la fin d'un geste et l'envoi du suivant. */
    const val MARGE_MS = 15L
    const val APPUI_MIN_MS = 10L

    /** Temps doigt levé entre deux appuis sur la même touche. */
    const val RELACHE_MS = 10L

    /** Appuis courts : un geste plus long ne pourrait plus être interrompu, la pause attendrait sa fin. */
    const val PORTEE_MAX_MS = 600L

    /** Notes tenues : des gestes plus longs, sinon presque toutes les tenues seraient coupées. */
    const val PORTEE_TENUE_MS = 1500L

    /** Une note n'est jamais tenue plus longtemps (max_hold côté PC : 4 s ; ici la pause attend la fin du geste). */
    const val TENUE_MAX_MS = 2000L

    /** Android refuse un geste de plus de 20 traits (GestureDescription.getMaxStrokeCount). */
    const val MAX_TRAITS = 20

    /**
     * Les appuis à partir de [depuisMs], en temps réel (vitesse appliquée), sans deux appuis mêlés sur une touche.
     * [tenue] : chaque touche reste enfoncée la durée de sa note (bornée par [tenueMaxMs], jamais moins que
     * [appuiMs]) ; sinon tous les appuis durent [appuiMs]. Comme build_timeline de core.py, une touche rejouée
     * est relâchée juste avant.
     */
    fun traits(
        frappes: List<Frappe>, nbTouches: Int, vitesse: Float, depuisMs: Long, appuiMs: Long,
        tenue: Boolean = false, tenueMaxMs: Long = TENUE_MAX_MS,
    ): List<Trait> {
        val traits = ArrayList<Trait>()
        val dernier = arrayOfNulls<Trait>(nbTouches)
        for (f in frappes) {
            if (f.tMs < depuisMs) continue
            val debut = ((f.tMs - depuisMs) / vitesse).toLong()
            for ((rang, k) in f.touches.withIndex()) {
                if (k < 0 || k >= nbTouches) continue
                val avant = dernier[k]
                if (avant != null) {
                    val ecart = debut - avant.debut
                    // Trop près de l'appui précédent sur la même touche : le jeu n'en verrait qu'un.
                    if (ecart < 2 * APPUI_MIN_MS + RELACHE_MS) continue
                    if (avant.duree > ecart - RELACHE_MS) avant.duree = ecart - RELACHE_MS
                }
                val note = f.durees?.getOrNull(rang)
                val duree = if (tenue && note != null) max(appuiMs, min((note / vitesse).toLong(), tenueMaxMs)) else appuiMs
                val trait = Trait(debut, duree, k)
                dernier[k] = trait
                traits.add(trait)
            }
        }
        return traits
    }

    /**
     * Indice de fin (exclu) du geste qui commence en [i] : il avale tous les appuis qui démarrent avant
     * qu'il soit fini. S'il faut le couper quand même (trop d'appuis ou trop long), ses appuis sont
     * raccourcis pour finir avant le geste suivant.
     *
     * [ecartPropre] : écart minimal entre deux débuts d'appui pour couper entre eux. Couper juste après un
     * appui ne lui laisserait que quelques millisecondes ; passé deux fois [porteeMs], on coupe quand même
     * au premier changement d'instant. Un accord n'est jamais partagé entre deux gestes tant qu'il tient
     * dans [maxTraits].
     */
    fun finDuGeste(
        traits: List<Trait>, i: Int,
        maxTraits: Int = MAX_TRAITS, porteeMs: Long = PORTEE_MAX_MS, ecartPropre: Long = 1,
    ): Int {
        val debut = traits[i].debut
        var fin = debut + traits[i].duree
        var j = i + 1
        // Dernier endroit où couper sans partager un accord, si le geste se remplit avant d'être fini.
        var repli = -1
        while (j < traits.size) {
            val t = traits[j]
            if (t.debut > fin + MARGE_MS) return j
            val ecart = t.debut - traits[j - 1].debut
            if (ecart > 0) repli = j
            val plein = j - i >= maxTraits
            val long = t.debut - debut > porteeMs && ecart >= ecartPropre
            val tropLong = t.debut - debut > 2 * porteeMs && ecart > 0
            if (plein || long || tropLong) {
                val coupe = if (plein && ecart <= 0 && repli > i) repli else j
                val limite = traits[coupe].debut - MARGE_MS
                for (k in i until coupe) {
                    val reste = limite - traits[k].debut
                    if (traits[k].duree > reste) traits[k].duree = max(APPUI_MIN_MS, reste)
                }
                return coupe
            }
            fin = max(fin, t.debut + t.duree)
            j++
        }
        return j
    }

    /** Tous les gestes du morceau, dans l'ordre. Les durées des [traits] sont ajustées en place. */
    fun decouper(traits: List<Trait>, tenue: Boolean = false, appuiMs: Long = 0, maxTraits: Int = MAX_TRAITS): List<List<Trait>> {
        val gestes = ArrayList<List<Trait>>()
        var i = 0
        while (i < traits.size) {
            val j = if (tenue) finDuGeste(traits, i, maxTraits, PORTEE_TENUE_MS, appuiMs + MARGE_MS)
            else finDuGeste(traits, i, maxTraits)
            gestes.add(traits.subList(i, j))
            i = j
        }
        return gestes
    }
}
