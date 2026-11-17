/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { NavBar } from "@web/webclient/navbar/navbar";

patch(NavBar.prototype, "logistica_base.BitacoraSidebar", {
    async adapt() {
        if (window.innerWidth >= 768) {
            const hadExtra = this.currentAppSectionsExtra && this.currentAppSectionsExtra.length > 0;
            this.currentAppSectionsExtra = [];
            if (this.appSubMenus && this.appSubMenus.el) {
                const sections = this.appSubMenus.el.querySelectorAll(":scope > *:not(.o_menu_sections_more)");
                for (const section of sections) {
                    section.classList.remove("d-none");
                }
            }
            if (hadExtra) {
                return this.render();
            }
            return;
        }
        return this._super(...arguments);
    },
});
