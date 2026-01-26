"""Command-line interface for Staff Finder."""

import asyncio
import logging
import sys
from pathlib import Path
import click
import pandas as pd
from .processor import StaffFinder


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@click.command()
@click.argument('input_csv', type=click.Path(exists=True))
@click.option(
    '--output', '-o',
    type=click.Path(),
    help='Output CSV file path (default: adds _with_urls suffix to input file)'
)
@click.option(
    '--jina-api-key',
    envvar='JINA_API_KEY',
    help='Jina API key (or set JINA_API_KEY environment variable)'
)
@click.option(
    '--openai-api-key',
    envvar='OPENAI_API_KEY',
    required=True,
    help='OpenAI API key (or set OPENAI_API_KEY environment variable)'
)
@click.option(
    '--openai-model',
    default='gpt-4o-mini',
    help='OpenAI model to use (default: gpt-4o-mini)'
)
@click.option(
    '--max-concurrent',
    default=5,
    type=int,
    help='Maximum number of concurrent requests (default: 5)'
)
@click.option(
    '--verbose', '-v',
    is_flag=True,
    help='Enable verbose logging'
)
def main(input_csv, output, jina_api_key, openai_api_key, openai_model, max_concurrent, verbose):
    """Staff Finder - Discover staff directory URLs for K-12 schools.
    
    Reads a CSV file containing school records and automatically finds
    staff directory URLs using Jina Search API and OpenAI reasoning.
    
    The input CSV should contain at least these columns:
    - name: School name
    - city: City where school is located
    - state: State where school is located
    
    Example:
    
        staff-finder schools.csv -o schools_with_urls.csv
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Determine output file path
    if not output:
        input_path = Path(input_csv)
        output = input_path.parent / f"{input_path.stem}_with_urls{input_path.suffix}"
    
    logger.info(f"Reading schools from: {input_csv}")
    
    try:
        # Read input CSV
        df = pd.read_csv(input_csv)
        
        # Validate required columns
        required_columns = ['name']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns in CSV: {missing_columns}")
            logger.info(f"Available columns: {list(df.columns)}")
            sys.exit(1)
        
        # Add optional columns if missing
        if 'city' not in df.columns:
            df['city'] = ''
        if 'state' not in df.columns:
            df['state'] = ''
        
        logger.info(f"Found {len(df)} schools to process")
        
        # Convert DataFrame to list of dictionaries
        school_records = df.to_dict('records')
        
        # Initialize Staff Finder
        finder = StaffFinder(
            jina_api_key=jina_api_key,
            openai_api_key=openai_api_key,
            openai_model=openai_model,
            max_concurrent=max_concurrent
        )
        
        # Process schools
        logger.info("Starting to find staff directory URLs...")
        results = asyncio.run(finder.find_staff_urls_batch(school_records))
        
        # Convert results back to DataFrame
        results_df = pd.DataFrame(results)
        
        # Save to output file
        results_df.to_csv(output, index=False)
        logger.info(f"Results saved to: {output}")
        
        # Print summary
        found_count = results_df['staff_url'].notna().sum()
        logger.info(f"\nSummary:")
        logger.info(f"  Total schools: {len(results_df)}")
        logger.info(f"  URLs found: {found_count}")
        logger.info(f"  Not found: {len(results_df) - found_count}")
        
        # Print confidence breakdown for found URLs
        if found_count > 0:
            confidence_counts = results_df[results_df['staff_url'].notna()]['confidence'].value_counts()
            logger.info(f"\nConfidence levels:")
            for conf, count in confidence_counts.items():
                logger.info(f"  {conf}: {count}")
        
    except FileNotFoundError:
        logger.error(f"Input file not found: {input_csv}")
        sys.exit(1)
    except pd.errors.EmptyDataError:
        logger.error(f"Input CSV file is empty: {input_csv}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=verbose)
        sys.exit(1)


if __name__ == '__main__':
    main()
