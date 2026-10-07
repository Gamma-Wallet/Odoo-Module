-- A neutralized copy (Odoo.sh staging, odoo-bin neutralize) is disconnected from Gamma, so it never
-- creates real rewards or store-credit requests for the live business.
DELETE FROM ir_config_parameter WHERE key IN ('gamma_wallet.token', 'gamma_wallet.connection');
