import logging

from scout.utils.md5 import generate_md5_key
from scout.parse.genotype import parse_genotypes
from scout.parse.compound import parse_compounds
from scout.parse.clnsig import parse_clnsig
from scout.parse.gene import parse_genes
from scout.parse.frequency import parse_frequencies
from scout.parse.conservation import parse_conservations
from scout.parse.ids import parse_ids
from scout.parse.callers import parse_callers

from scout.exceptions import VcfError

logger = logging.getLogger(__name__)

def get_coordinates(ref, alt, position, category, svtype, svlen, end, mate_id=None):
    """Find out the coordinates for a variant
    
        Args:
            ref(str)
            alt(str)
            position(int)
            category(str)
            svtype(str)
            svlen(int)
            end(int)
            mate_id(str)
        
        Returns:
            coordinates(dict): A dictionary on the form:
            {
                'end':<int>, 
                'length':<int>, 
                'sub_category':<str>,
                'mate_id':<str>,
            }
    """
    coordinates = {
        'end': None,
        'length': None,
        'sub_category': None,
        'mate_id':None,
    }
    if category == 'snv':
        ref_len = len(ref)
        alt_len = len(alt)
        # If lenth is same lenth is same as alternative
        if ref_len == alt_len:
            coordinates['length'] = alt_len
            coordinates['end'] = variant['position'] + (alt_len -1)
            if alt_len == 1:
                coordinates['sub_category'] = 'snv'
            else:
                coordinates['sub_category'] = 'indel'
        # Ref > Alt we have an deletion
        elif ref_len > alt_len:
            coordinates['length'] = ref_len - alt_len
            coordinates['end'] = position + (ref_len - 1)
            coordinates['sub_category'] = 'indel'
        # Alt > Ref we have an insertion
        elif ref_len < alt_len:
            coordinates['length'] = alt_len - ref_len
            coordinates['end'] = variant['position'] + (alt_len - 1)
            coordinates['sub_category'] = 'indel'

    elif variant['category'] == 'sv':
        if svtype:
            coordinates['sub_category'] = svtype
        else:
            raise VcfError("SVs has to have SVTYPE")
        
        if variant['sub_category'] == 'bnd':
            if mate_id:
                coordinates['mate_id'] = mate_id
            #For translocations we set lenth to infinity
            coordinates['length'] = int(10e10)
            coordinates['end'] = int(10e10)
        else:
            if svlen:
                coordinates['length'] = abs(int(svlen))
            else:
                # -1 would indicate uncertain length
                coordinates['length'] = -1

            coordinates['end'] = int(end)

    return coordinates
    

def parse_variant(variant_dict, case, variant_type='clinical', rank_results_header=None):
    """Return a parsed variant

        Get all the necessary information to build a variant object

        Args:
            variant_dict(dict): A dictionary from VCFParser
            case(dict)
            variant_type(str): 'clinical' or 'research'

        Yields:
            variant(dict): Parsed variant
    """
    rank_results_header = rank_results_header or []
    variant = {}
    # Create the ID for the variant
    case_id = case['case_id']
    case_name = case['display_name']

    variant['ids'] = parse_ids(variant_dict, case, variant_type)
    variant['case_id'] = case_id
    # type can be 'clinical' or 'research'
    # category is sv or snv
    if variant_dict['info_dict'].get('SVTYPE'):
        variant['category'] = 'sv'
    else:
        variant['category'] = 'snv'
    #sub category is 'snv', 'indel', 'del', 'ins', 'dup', 'inv', 'cnv'
    # 'snv' and 'indel' are subcatogories of snv
    variant['sub_category'] = None

    ################# General information #################

    variant['reference'] = variant_dict['REF']
    variant['alternative'] = variant_dict['ALT']
    variant['quality'] = float(variant_dict['QUAL'])
    variant['filters'] = variant_dict['FILTER'].split(';')
    variant['variant_type'] = variant_type
    # This is the id of other position in translocations
    variant['mate_id'] = None

    ################# Position specific #################
    variant['chromosome'] = variant_dict['CHROM']
    # position = start
    variant['position'] = int(variant_dict['POS'])
    
    sv_type = variant_dict['info_dict'].get('SVTYPE')
    if sv_type:
        svtype = svtype[0]
    svlen = variant_dict['info_dict'].get('SVLEN')
    if svlen:
        svlen = svlen[0]
    end = variant_dict['info_dict'].get('END')
    if end:
        end = end[0]
    mate_id = variant_dict['info_dict'].get('MATEID')
    if mate_id:
        mate_id = mate_id[0]
    
    coordinates = get_coordinates(
        ref=variant['reference'], 
        alt=variant['alternative'],
        position=variant['position'],
        category=variant['category'], 
        svtype=svtype, 
        svlen=svlen, 
        end=end,
        mate_id=end,
    )
    
    variant['sub_category'] = coordinates['sub_category']
    variant['mate_id'] = coordinates['mate_id']
    variant['end'] = coordinates['end']
    variant['length'] = coordinates['length']

    ################# Add the rank score #################
    # The rank score is central for displaying variants in scout.

    rank_score = float(variant_dict.get('rank_scores', {}).get(case_name, 0.0))
    variant['rank_score'] = rank_score

    ################# Add gt calls #################

    variant['samples'] = parse_genotypes(variant_dict, case)

    ################# Add the compound information #################

    variant['compounds'] = parse_compounds(
                                variant=variant_dict,
                                case=case,
                                variant_type=variant_type
                                )

    ################# Add the inheritance patterns #################

    genetic_models = variant_dict.get('genetic_models',{}).get(case_name,[])
    variant['genetic_models'] = genetic_models

    # Add the clinsig prediction
    clnsig_accessions = get_clnsig(variant_dict)
    if clnsig_accessions:
        variant['clnsig'] = 5
        variant['clnsigacc'] = clnsig_accessions
    else:
        variant['clnsig'] = None
        variant['clnsigacc'] = None

    ################# Add the gene and transcript information #################

    variant['genes'] = parse_genes(variant_dict)

    hgnc_symbols = set([])
    ensembl_gene_ids = set([])

    for gene in variant['genes']:
        hgnc_symbols.add(gene['hgnc_symbol'])
        ensembl_gene_ids.add(gene['ensembl_gene_id'])

    variant['hgnc_symbols'] = list(hgnc_symbols)
    variant['ensembl_gene_ids'] = list(ensembl_gene_ids)

    ################# Add a list with the dbsnp ids #################

    variant['db_snp_ids'] = variant_dict['ID'].split(';')

    ################# Add the frequencies #################

    variant['frequencies'] = parse_frequencies(variant_dict)

    # Add the severity predictions
    cadd = variant_dict['info_dict'].get('CADD')
    if cadd:
        value = cadd[0]
        variant['cadd_score'] = float(value)

    spidex = variant_dict['info_dict'].get('SPIDEX')
    if spidex:
        value = spidex[0]
        variant['spidex'] = spidex

    variant['conservation'] = parse_conservations(variant_dict)

    variant['callers'] = parse_callers(variant_dict)
    
    rank_result = variant_dict['info_dict'].get('RankResult')
    if rank_result:
        results = [int(i) for i in rank_result[0].split('|')]
        variant['rank_result'] = dict(zip(rank_results_header, results))
    

    return variant
