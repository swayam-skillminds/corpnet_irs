import os
...
def get_salesforce_connection(domain='test'):
    try:
        sf = Salesforce(
            username=os.environ.get('nrajput@skillminds.in.corpnet.fullphase2'),
            password=os.environ.get('navi@1234'),
            security_token=os.environ.get('lBMegvFQAo07grFQUrkZ7Y3g'),
            domain=domain
        )
        return sf
    except Exception as e:
        print(f"Failed to connect to Salesforce: {e}")
        return None
