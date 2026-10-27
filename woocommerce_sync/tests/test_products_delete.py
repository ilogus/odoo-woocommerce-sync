"""Tests for 'woocommerce_to_odoo_products_delete()': products no longer published in WooCommerce are archived in Odoo, and products gone from WooCommerce are deleted, or archived when Odoo refuses to delete them (e.g. used in a sale order), instead of failing the job."""

from unittest.mock import MagicMock, patch

from odoo.tests.common import tagged

from .common import WoocommerceSyncCommon


@tagged('post_install', '-at_install')
class TestProductsDelete(WoocommerceSyncCommon):
    def _create_odoo_product(self, woocommerce_id: int, name: str):
        return self.env['product.template'].create(
            {
                'name': name,
                'woocommerce_site_url': self.connector.settings_woocommerce_connection_url,
                'woocommerce_id': str(woocommerce_id),
                'woocommerce_status': 'publish',
            }
        )

    def _run_products_delete(self, woocommerce_products: list[dict]) -> None:
        with (
            patch.object(type(self.connector), 'woocommerce_api_get', return_value=MagicMock()),
            patch.object(type(self.connector), 'woocommerce_api_get_all_items', return_value=woocommerce_products) as mocked_get_all_items,
        ):
            self.connector.woocommerce_to_odoo_products_delete()

        self.assertEqual(mocked_get_all_items.call_args.kwargs['params']['_fields'], 'id,status')

    def test_unpublished_product_is_archived(self):
        published = self._create_odoo_product(94001, 'Published product')
        draft = self._create_odoo_product(94002, 'Draft product')
        private = self._create_odoo_product(94003, 'Private product')

        self._run_products_delete([{'id': 94001, 'status': 'publish'}, {'id': 94002, 'status': 'draft'}, {'id': 94003, 'status': 'private'}])

        self.assertTrue(published.active)
        self.assertFalse(draft.active, 'A product set back to draft in WooCommerce is archived even if its webhook was missed')
        self.assertEqual(draft.woocommerce_status, 'draft')
        self.assertFalse(draft.product_variant_ids.active)
        self.assertFalse(private.active)

    def test_deleted_product_is_deleted(self):
        deleted = self._create_odoo_product(94011, 'Deleted product')

        self._run_products_delete([])

        self.assertFalse(deleted.exists())

    def test_deleted_product_used_in_a_sale_is_archived(self):
        sold = self._create_odoo_product(94021, 'Sold product')
        unsold = self._create_odoo_product(94022, 'Unsold product')
        partner = self.env['res.partner'].create({'name': 'Products delete customer'})
        self.env['sale.order'].create({'partner_id': partner.id, 'order_line': [(0, 0, {'product_id': sold.product_variant_id.id, 'product_uom_qty': 1, 'price_unit': 5.0})]})

        self._run_products_delete([])

        self.assertTrue(sold.exists(), 'A product with sales history cannot be deleted')
        self.assertFalse(sold.active, 'It is archived instead, so the job does not fail')
        self.assertFalse(unsold.exists(), 'The other deleted products are still deleted')
